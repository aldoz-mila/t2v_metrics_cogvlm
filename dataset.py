import os
import json
import subprocess
import numpy as np
import pandas as pd
import torchvision
import torch

from PIL import Image
from tqdm import tqdm
from torch.utils.data import Dataset
from scipy.stats import kendalltau

def get_winoground_scores(scores_i2t):
    ids = list(range(scores_i2t.shape[0]))
    winoground_scores = []
    for id, score_i2t in zip(ids, scores_i2t):
        winoground_scores.append({
            "id" : id,
            "c0_i0": score_i2t[0][0],
            "c0_i1": score_i2t[1][0],
            "c1_i0": score_i2t[0][1],
            "c1_i1": score_i2t[1][1]}
        )
    return winoground_scores

def get_winoground_acc(scores):
    text_correct_count = 0
    image_correct_count = 0
    group_correct_count = 0
    def text_correct(result):
        return result["c0_i0"] > result["c1_i0"] and result["c1_i1"] > result["c0_i1"]

    def image_correct(result):
        return result["c0_i0"] > result["c0_i1"] and result["c1_i1"] > result["c1_i0"]

    def group_correct(result):
        return image_correct(result) and text_correct(result)
    
    for result in scores:
        text_correct_count += 1 if text_correct(result) else 0
        image_correct_count += 1 if image_correct(result) else 0
        group_correct_count += 1 if group_correct(result) else 0

    denominator = len(scores)
    result = {
        'text': text_correct_count/denominator,
        'image': image_correct_count/denominator,
        'group': group_correct_count/denominator,
    }
    return result


class Winoground(Dataset):
    def __init__(self, image_preprocess=None, root_dir='./', return_image_paths=True):
        self.root_dir = os.path.join(root_dir, "winoground")
        if not os.path.exists(self.root_dir):
            subprocess.call(
                ["gdown", "--no-cookies", "1Lril_90vjsbL_2qOaxMu3I-aPpckCDiF", "--output",
                 os.path.join(root_dir, "winoground.zip")]
            )
            subprocess.call(
                ["unzip", "-q", "winoground.zip"],
                cwd=root_dir
            )
        csv_file = os.path.join(self.root_dir, 'metadata.csv')
        self.metadata = pd.read_csv(csv_file).to_dict(orient='records')
        json_file = os.path.join(self.root_dir, 'examples.jsonl')
        self.winoground = [json.loads(line) for line in open(json_file, 'r')]
        self.return_image_paths = return_image_paths
        if return_image_paths:
            assert image_preprocess is None
            self.preprocess = None
            
        self.preprocess = image_preprocess
        self.original_tags = self.get_original_tags()
        self.new_tags = self.get_new_tags(path=os.path.join(self.root_dir, "why_winoground_hard.json"))
    
    def __len__(self):
        return len(self.winoground)

    def __getitem__(self, idx):
        assert self.metadata[idx]['id'] == idx
        image_0_path = os.path.join(self.root_dir, self.metadata[idx]['image_0'])
        image_1_path = os.path.join(self.root_dir, self.metadata[idx]['image_1'])
        if self.return_image_paths:
            image_0 = image_0_path
            image_1 = image_1_path
        else:
            image_0 = self.preprocess(self.image_loader(image_0_path))
            image_1 = self.preprocess(self.image_loader(image_1_path))
        
        caption_0 = self.metadata[idx]['caption_0']
        caption_1 = self.metadata[idx]['caption_1']
        item = {
            "images": [image_0, image_1],
            "texts": [caption_0, caption_1]
        }
        return item
    
    def get_original_tags(self):
        tags = {}
        for example in self.winoground:
            if example['num_main_preds'] == 1:
                if '1 Main Pred' not in tags:
                    tags["1 Main Pred"] = []
                tags['1 Main Pred'].append(example["id"])
            elif example['num_main_preds'] == 2:
                if '2 Main Pred' not in tags:
                    tags["2 Main Pred"] = []
                tags['2 Main Pred'].append(example["id"])
            else:
                # This won't happen
                raise ValueError(f"num_main_preds: {example['num_main_preds']}")
            if example["collapsed_tag"] not in tags:
                tags[example["collapsed_tag"]] = []
            tags[example["collapsed_tag"]].append(example["id"])
        return tags

    def get_new_tags(self, path="./why_winoground_hard.json"):
        new_tag_dict = json.load(open(path))
        tags = {}
        for idx in new_tag_dict:
            curr_tags = new_tag_dict[idx]
            if len(curr_tags) == 0:
                if "No Tag" not in tags:
                    tags["No Tag"] = []
                tags["No Tag"].append(int(idx))
            for tag in curr_tags:
                if tag not in tags:
                    tags[tag] = []
                tags[tag].append(int(idx))
        return tags
    
    
    def evaluate_scores(self, scores):
        winoground_scores = get_winoground_scores(scores)
        acc = get_winoground_acc(winoground_scores)
        print("Winoground performance (overall)")
        print(f"{'Dataset': <70} {'Text': <10} {'Image': <10} {'Group': <10}")
        print(f"{'Winoground': <70} {acc['text']: <10.2%} {acc['image']: <10.2%} {acc['group']: <10.2%}")
        results = {}
        results['all'] = acc
        for tag in self.original_tags:
            results[tag] = get_winoground_acc([winoground_scores[i] for i in self.original_tags[tag]])
        for tag in self.new_tags:
            results[tag] = get_winoground_acc([winoground_scores[i] for i in self.new_tags[tag]])
            # print(f"Winoground {tag} text score: {results[tag]['text']}")
            # print(f"Winoground {tag} image score: {results[tag]['image']}")
            # print(f"Winoground {tag} group score: {results[tag]['group']}")
        return results, acc['group']


class SugarCrepe(Dataset):
    def __init__(self, image_preprocess=None, root_dir="./", return_image_paths=True):
        self.root_dir = os.path.join(root_dir, 'coco2017')
        if not os.path.exists(self.root_dir):
            os.makedirs(self.root_dir, exist_ok=True)
            import subprocess
            subprocess.call(['wget', 'http://images.cocodataset.org/zips/val2017.zip'], cwd=self.root_dir)
            subprocess.call(['unzip', "-q", 'val2017.zip'], cwd=self.root_dir)
        self.root_dir = os.path.join(root_dir, 'coco2017', 'val2017')
        
        data_dict = {
            'add_obj'    : f'datasets/sugar_crepe/add_obj.json',
            'add_att'    : f'datasets/sugar_crepe/add_att.json',
            'replace_obj': f'datasets/sugar_crepe/replace_obj.json',
            'replace_att': f'datasets/sugar_crepe/replace_att.json',
            'replace_rel': f'datasets/sugar_crepe/replace_rel.json',
            'swap_obj'   : f'datasets/sugar_crepe/swap_obj.json',
            'swap_att'   : f'datasets/sugar_crepe/swap_att.json',
        }
        self.dataset = {}
        for hard_neg_type in data_dict:
            self.dataset[hard_neg_type] = json.load(open(data_dict[hard_neg_type], 'r', encoding='utf-8'))
        
        self.image_preprocess = image_preprocess
        self.items = []
        self.hard_neg_type_to_indices = {hard_neg_type: [] for hard_neg_type in self.dataset}
        ctr = 0
        for hard_neg_type in self.dataset:
            for idx in self.dataset[hard_neg_type]:
                self.items.append([hard_neg_type, idx])
                self.hard_neg_type_to_indices[hard_neg_type].append(ctr)
                ctr += 1
        self.return_image_paths = return_image_paths

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        hard_neg_type, idx = self.items[idx]
        image_path = os.path.join(self.root_dir, self.dataset[hard_neg_type][idx]['filename'])
        if self.return_image_paths:
            image = image_path
        else:
            image = Image.open(image_path).convert('RGB')
            image = self.image_preprocess(image)
        texts = [str(self.dataset[hard_neg_type][idx]['caption']), self.dataset[hard_neg_type][idx]['negative_caption']]
        item = {"images": [image], "texts": texts}
        return item
    
    def evaluate_scores(self, scores):
        scores_i2t = scores.cpu().numpy()
        results_by_type = {}
        
        preds = np.argmax(np.squeeze(scores_i2t, axis=1), axis=-1)
        correct_mask = (preds == 0)
        result_records = [{"Precision@1": np.mean(correct_mask)}]
        df = pd.DataFrame(result_records)
        macro_accuracy = df['Precision@1'].mean()
        print(f"SugarCrepe Macro Accuracy: {macro_accuracy}")
        for hard_neg_type in self.hard_neg_type_to_indices:
            indices = self.hard_neg_type_to_indices[hard_neg_type]
            correct_mask = (preds[indices] == 0)
            result_records = [{"Precision@1": np.mean(correct_mask)}]
            df = pd.DataFrame(result_records)
            macro_accuracy = df['Precision@1'].mean()
            results_by_type[hard_neg_type] = macro_accuracy
            print(f"SugarCrepe {hard_neg_type} Macro Accuracy: {macro_accuracy}")
        
        add_accuracy = (results_by_type['add_obj'] + results_by_type['add_att']) / 2
        replace_accuracy = (results_by_type['replace_obj'] + results_by_type['replace_att'] + results_by_type['replace_rel']) / 3
        swap_accuracy = (results_by_type['swap_obj'] + results_by_type['swap_att']) / 2
        print("SugarCrepe performance (by tag)")
        print(f"{'Dataset': <70} {'Add': <10} {'Replace': <10} {'Swap': <10}")
        print(f"{'SugarCrepe': <70} {add_accuracy: <10.2%} {replace_accuracy: <10.2%} {swap_accuracy: <10.2%}")
        return result_records, macro_accuracy
    

class TIFA160_DSG(Dataset):
    def __init__(self, image_preprocess=None, root_dir="./", download=True, return_image_paths=True):
        self.root_dir = os.path.join(root_dir, 'tifa160')
        if not os.path.exists(self.root_dir):
            if download:
                os.makedirs(root_dir, exist_ok=True)
                import subprocess
                image_zip_file = os.path.join(root_dir, "tifa160.zip")
                subprocess.call(
                    ["gdown", "--no-cookies", "1hHVMeVDZlnJz1FFhy_BxiZGIz1tEMm0s", "--output",
                     image_zip_file]
                )
                subprocess.call(["unzip", "-q", "tifa160.zip"], cwd=root_dir)
        
        self.dataset = json.load(open(os.path.join("datasets", "tifa160.json"), 'r'))
        self.dsg_human_likert_scores = pd.read_csv(os.path.join("datasets", "dsg_tifa160_anns.csv"))
        self.model_type_to_names = {
            'mini-dalle': 'mini_dalle',
            'vq-diffusion': 'vq_diffusion',
            'sd1dot5': 'stable_diffusion_v1_5',
            'sd2dot1': 'stable_diffusion_v2_1',
            'sd1dot1': 'stable_diffusion_v1_1',
        }
        self.model_types = [self.model_type_to_names[m_name] for m_name in self.dsg_human_likert_scores['model_type'].to_list()]
        self.source_ids = self.dsg_human_likert_scores['source_id'].to_list()
        self.keys = [f"{self.source_ids[idx]}_{self.model_types[idx]}" for idx in range(len(self.model_types))]
        self.path_names = [f"{k}.jpg" for k in self.keys]
        # self.item_ids = self.dsg_human_likert_scores['item_id'].to_list()
        self.answers = self.dsg_human_likert_scores['answer'].to_list()
        self.dsg_items = {}
        for key_idx, k in enumerate(self.keys):
            if k in self.dsg_items:
                self.dsg_items[k]['human_scores'].append(self.answers[key_idx])
            else:
                self.dsg_items[k] = {
                    'human_scores': [self.answers[key_idx]],
                    'text': self.dataset[self.keys[key_idx]]['text'],
                    'image_path': self.path_names[key_idx],
                    'text_id': self.source_ids[key_idx],
                }
        
        # compute 'human_avg'
        for k in self.dsg_items:
            self.dsg_items[k]['human_avg'] = float(np.mean(self.dsg_items[k]['human_scores']))
            assert self.dsg_items[k]['text_id'] == self.dataset[k]['text_id']
            assert self.dsg_items[k]['text'] == self.dataset[k]['text']
            assert self.dsg_items[k]['image_path'] == self.dataset[k]['image_path']
        self.image_preprocess = image_preprocess
        self.items = list(self.dataset.keys())
        self.return_image_paths = return_image_paths
    
    def __len__(self):
        return len(self.dataset)

    def __getitem__(self, idx):
        k = self.items[idx]
        item = self.dataset[k]
        
        image_path = os.path.join(self.root_dir, item['image_path'])
        if self.return_image_paths:
            image = image_path
        else:
            image = Image.open(image_path).convert('RGB')
            image = self.image_preprocess(image)
        
        texts = [str(item['text'])]
        item = {"images": [image], "texts": texts}
        return item
    
    def evaluate_scores(self, scores):
        scores_i2t = scores
        human_avg_scores = self.get_metric_scores('human_avg')
        our_scores = [float(scores_i2t[idx][0][0]) for idx in range(len(self.items))]
        import math
        human_avg_scores_without_nan = []
        our_scores_without_nan = []
        for idx in range(len(self.items)):
            if math.isnan(our_scores[idx]):
                print(f"Warning: {self.items[idx]} has nan score! Skipping this for evaluation")
                continue
            human_avg_scores_without_nan.append(human_avg_scores[idx])
            our_scores_without_nan.append(our_scores[idx])
        spearman, kendall = self.compute_correlation(human_avg_scores_without_nan, our_scores_without_nan)
        print(f"Spearman's Correlation (ours): ", spearman)
        print(f'Kendall Tau Score (ours): ', kendall)
        return spearman, kendall
    
    def get_metric_scores(self, metric):
        if metric == 'human_avg':
            return [self.dsg_items[k][metric] for k in self.items]
        return [self.dataset[k][metric] for k in self.items]
    
    def compute_correlation(self, metric1_scores, metric2_scores):
        spearman = np.corrcoef(metric1_scores, metric2_scores)[0, 1]
        kendall = kendalltau(metric1_scores, metric2_scores)
        return spearman, kendall


class EqBen_Mini(Dataset):
    def __init__(self, image_preprocess=None, root_dir='./', return_image_paths=True):
        self.preprocess = image_preprocess
        
        self.root_dir = os.path.join(root_dir, "eqben_vllm")
        if not os.path.exists(self.root_dir):
            # https://drive.google.com/file/d/11YUTf06uzRHtFV8rYi96z4vTPi8_GNEM/view?usp=sharing
            os.makedirs(self.root_dir, exist_ok=True)
            subprocess.call(
                ["gdown", "--no-cookies", "11YUTf06uzRHtFV8rYi96z4vTPi8_GNEM", "--output", 
                 os.path.join(self.root_dir, "eqben_vllm.zip")]
            )
            subprocess.call(["unzip", "-q", "eqben_vllm.zip"], cwd=self.root_dir)
            
        self.root_dir = os.path.join(root_dir, "eqben_vllm", "images")
        self.subset_types = {
            'eqbensd': ['eqbensd'],
            'eqbenk': ['eqbenkubric_cnt', 'eqbenkubric_loc', 'eqbenkubric_attr'],
            'eqbeng': ['eqbengebc'],
            'eqbenag': ['eqbenag'],
            'eqbeny': ['eqbenyoucook2'],
        }
        json_file = os.path.join(root_dir, "eqben_vllm", "all_select.json")
        self.metadata = json.load(open(json_file, 'r'))
        self.subset_indices = {subset_type: [] for subset_type in self.subset_types}
        for item_idx, item in enumerate(self.metadata):
            image_path = item['image0']
            for subset_type in self.subset_types:
                if image_path.split('/')[0] in self.subset_types[subset_type]:
                    self.subset_indices[subset_type].append(item_idx)
                    break
        
        self.return_image_paths = return_image_paths
        self.transform = image_preprocess
        if self.return_image_paths:
            assert self.transform is None, "Cannot return image paths and apply transforms"
     
    def __len__(self):
        return len(self.metadata)
    
    def __getitem__(self, index):
        image_0_path = os.path.join(self.root_dir, self.metadata[index]['image0'])
        image_1_path = os.path.join(self.root_dir, self.metadata[index]['image1'])
        if self.return_image_paths:
            image_0 = image_0_path
            image_1 = image_1_path
        else:
            image_0 = self.transform(self.image_loader(image_0_path))
            image_1 = self.transform(self.image_loader(image_1_path))
        
        caption_0 = self.metadata[index]['caption0']
        caption_1 = self.metadata[index]['caption1']
        item = {"images": [image_0, image_1], "texts": [caption_0, caption_1]}
        return item
    
    def evaluate_scores(self, scores):
        winoground_scores = get_winoground_scores(scores)
        acc = get_winoground_acc(winoground_scores)
        print("EQBen_Mini performance (overall)")
        print(f"{'Dataset': <70} {'Text': <10} {'Image': <10} {'Group': <10}")
        print(f"{'EQBen_Mini': <70} {acc['text']: <10.2%} {acc['image']: <10.2%} {acc['group']: <10.2%}")
        results = {}
        results['all'] = acc
        for subset_type in self.subset_types:
            subset_indices = self.subset_indices[subset_type]
            subset_scores = [winoground_scores[idx] for idx in subset_indices]
            subset_acc = get_winoground_acc(subset_scores)
            print(f"{'EQBen_Mini ' + subset_type: <70} {subset_acc['text']: <10.2%} {subset_acc['image']: <10.2%} {subset_acc['group']: <10.2%}")
            results[subset_type] = subset_acc
        return results, acc['group']