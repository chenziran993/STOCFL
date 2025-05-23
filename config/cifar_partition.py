import sys


from fedlab.utils.functional import save_dict
from fedlab.utils.dataset.slicing import noniid_slicing, random_slicing

import torchvision

trainset = torchvision.datasets.CIFAR10(root="../datasets/cifar10", train=True, download=False)

num_clients=100
num_shards=200

data_indices = noniid_slicing(trainset, num_clients=num_clients, num_shards=num_shards)
save_dict(data_indices, "cifar10_noniid_{}_{}.pkl".format(num_clients, num_shards))

data_indices = random_slicing(trainset, num_clients=num_clients)
save_dict(data_indices, "cifar10_iid_{}.pkl".format(num_clients))