from __future__ import division

import torch
from torch_geometric.nn.pool import SAGPooling


def test_sag_pooling():
    in_channels = 16
    edge_index = torch.tensor([[0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3],
                               [1, 2, 3, 0, 2, 3, 0, 1, 3, 0, 1, 2]])
    num_nodes = edge_index.max().item() + 1
    x = torch.randn((num_nodes, in_channels))

    for gnn in ['GraphConv', 'GCN', 'GAT', 'SAGE']:
        pool = SAGPooling(in_channels, ratio=0.5, gnn=gnn)
        assert pool.__repr__() == ('SAGPooling({}, 16, ratio=0.5, '
                                   'multiplier=1)').format(gnn)
        out = pool(x, edge_index)
        assert out[0].size() == (num_nodes // 2, in_channels)
        assert out[1].size() == (2, 2)

        pool = SAGPooling(in_channels, ratio=None, gnn=gnn, min_score=0.1)
        assert pool.__repr__() == ('SAGPooling({}, 16, min_score=0.1, '
                                   'multiplier=1)').format(gnn)
        out = pool(x, edge_index)
        assert out[0].size(0) <= x.size(0) and out[0].size(1) == (16)
        assert out[1].size(0) == 2 and out[1].size(1) <= edge_index.size(1)
