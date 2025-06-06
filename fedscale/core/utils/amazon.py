from torch.utils.data import Dataset
import torch
import os
import pandas as pd

# This loader works for Amazon Review
# task : text_clf
class AmazonReview_loader(Dataset):
    def __init__(self, data_path, max_len, train=True, tokenizer=None ):

        file = 'train.csv' if train else 'test.csv'
        
        map_file = os.path.join(data_path, 'client_data_mapping', file)
        
        self.df = pd.read_csv(map_file, delimiter=',')
        # A reset reindexes from 1 to len(df), the shuffled df frames are sparse.
        self.df.reset_index(drop=True, inplace=True)
        self.tokenizer = tokenizer
        self.maxlen = max_len
        self.client_mapping = {}
        self.targets = []
        
        # TODO :not used
        # initiate the (sample, client) pairs
        for  row in  self.df.itertuples():
            (sample_id, client_id,data_path,label_name,label_id) = row
            client_id = int(client_id) - 1
            if client_id not in self.client_mapping:
                self.client_mapping[client_id] = []

            self.targets.append(float(label_name))
            self.client_mapping[client_id].append(sample_id)

    def __len__(self):
        return (len(self.df))

    def __getitem__(self, index):
        review = self.df.loc[index, 'data_path']

        # Classes start from 0.
        label = int(self.df.loc[index, 'label_name']) - 1

        # Use BERT tokenizer since it needs to be able to match the tokens to the pre trained words.
        tokens = self.tokenizer.tokenize(review)

        # BERT inputs typically start with a '[CLS]' tag and end with a '[SEP]' tag. For
        tokens = ['[CLS]'] + tokens + ['[SEP]']

        if len(tokens) < self.maxlen:
            # Add the ['PAD'] token
            tokens = tokens + ['[PAD]' for item in range(self.maxlen-len(tokens))]
        else:
            # Truncate the tokens at maxLen - 1 and add a '[SEP]' tag.
            tokens = tokens[:self.maxlen-1] + ['[SEP]']

        # BERT tokenizer converts the string tokens to their respective IDs.
        token_ids = self.tokenizer.convert_tokens_to_ids(tokens)

        # Converting to pytorch tensors.
        tokens_ids_tensor = torch.tensor(token_ids)

        # Masks place a 1 if token != PAD else a 0.
        attn_mask = (tokens_ids_tensor != 0).long()

        return (tokens_ids_tensor, attn_mask), label
