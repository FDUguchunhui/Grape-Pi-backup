import warnings
import inspect
from collections import OrderedDict

import torch
from torch_sparse import SparseTensor
from torch_scatter import scatter

msg_special_args = set([
    'edge_index',
    'edge_index_i',
    'edge_index_j',
    'size',
    'size_i',
    'size_j',
])

aggr_special_args = set([
    'index',
    'dim_size',
])

update_special_args = set([])


class MessagePassing(torch.nn.Module):
    r"""Base class for creating message passing layers of the form

    .. math::
        \mathbf{x}_i^{\prime} = \gamma_{\mathbf{\Theta}} \left( \mathbf{x}_i,
        \square_{j \in \mathcal{N}(i)} \, \phi_{\mathbf{\Theta}}
        \left(\mathbf{x}_i, \mathbf{x}_j,\mathbf{e}_{i,j}\right) \right),

    where :math:`\square` denotes a differentiable, permutation invariant
    function, *e.g.*, sum, mean or max, and :math:`\gamma_{\mathbf{\Theta}}`
    and :math:`\phi_{\mathbf{\Theta}}` denote differentiable functions such as
    MLPs.
    See `here <https://pytorch-geometric.readthedocs.io/en/latest/notes/
    create_gnn.html>`__ for the accompanying tutorial.

    Args:
        aggr (string, optional): The aggregation scheme to use
            (:obj:`"add"`, :obj:`"mean"` or :obj:`"max"`).
            (default: :obj:`"add"`)
        flow (string, optional): The flow direction of message passing
            (:obj:`"source_to_target"` or :obj:`"target_to_source"`).
            (default: :obj:`"source_to_target"`)
        node_dim (int, optional): The axis along which to propagate.
            (default: :obj:`0`)
    """
    def __init__(self, aggr="add", flow="source_to_target", node_dim=0):
        super(MessagePassing, self).__init__()

        self.aggr = aggr
        assert self.aggr in ['add', 'mean', 'max']

        self.flow = flow
        assert self.flow in ['source_to_target', 'target_to_source']

        self.node_dim = node_dim
        assert self.node_dim >= 0

        self.__msg_params__ = inspect.signature(self.message).parameters
        self.__msg_params__ = OrderedDict(self.__msg_params__)

        self.__aggr_params__ = inspect.signature(self.aggregate).parameters
        self.__aggr_params__ = OrderedDict(self.__aggr_params__)
        self.__aggr_params__.popitem(last=False)

        self.__update_params__ = inspect.signature(self.update).parameters
        self.__update_params__ = OrderedDict(self.__update_params__)
        self.__update_params__.popitem(last=False)

        msg_args = set(self.__msg_params__.keys()) - msg_special_args
        aggr_args = set(self.__aggr_params__.keys()) - aggr_special_args
        update_args = set(self.__update_params__.keys()) - update_special_args

        self.__args__ = set().union(msg_args, aggr_args, update_args)

    def __mp_type__(self, edge_index):
        if (torch.is_tensor(edge_index) and edge_index.dtype == torch.long
                and edge_index.dim() == 2 and edge_index.size(0)):
            return 'edge_index'
        elif isinstance(edge_index, SparseTensor):
            return 'adj_t'
        else:
            return ValueError(
                ('`MessagePassing` propagation only supports LongTensors of '
                 'shape `[2, num_messages]` or `torch_sparse.SparseTensor` '
                 'for argument :obj:`edge_index`.'))

    def __set_size__(self, size, idx, tensor):
        if not torch.is_tensor(tensor):
            pass
        elif size[idx] is None:
            size[idx] = tensor.size(self.node_dim)
        elif size[idx] != tensor.size(self.node_dim):
            raise ValueError(
                (f'Encountered node tensor with size '
                 f'{tensor.size(self.node_dim)} in dimension {self.node_dim}, '
                 f'but expected size {size[idx]}.'))

    def __collect__(self, edge_index, size, kwargs):
        i, j = (0, 1) if self.flow == 'target_to_source' else (1, 0)
        ij = {'_i': i, '_j': j}

        out = {}
        for arg in self.__args__:
            if arg[-2:] not in ij.keys():
                out[arg] = kwargs.get(arg, inspect.Parameter.empty)
            else:
                idx = ij[arg[-2:]]
                data = kwargs.get(arg[:-2], inspect.Parameter.empty)

                if data is inspect.Parameter.empty:
                    out[arg] = data
                    continue

                if isinstance(data, tuple) or isinstance(data, list):
                    assert len(data) == 2
                    self.__set_size__(size, 1 - idx, data[1 - idx])
                    data = data[idx]

                if not torch.is_tensor(data):
                    out[arg] = data
                    continue

                self.__set_size__(size, idx, data)
                out[arg] = data.index_select(self.node_dim, edge_index[idx])

        size[0] = size[1] if size[0] is None else size[0]
        size[1] = size[0] if size[1] is None else size[1]

        # Add special message arguments.
        out['edge_index'] = edge_index
        out['edge_index_i'] = edge_index[i]
        out['edge_index_j'] = edge_index[j]
        out['size'] = size
        out['size_i'] = size[i]
        out['size_j'] = size[j]

        # Add special aggregate arguments.
        out['index'] = out['edge_index_i']
        out['dim_size'] = out['size_i']

        return out

    def __distribute__(self, params, kwargs):
        out = {}
        for key, param in params.items():
            data = kwargs[key]
            if data is inspect.Parameter.empty:
                if param.default is inspect.Parameter.empty:
                    raise TypeError(f'Required parameter {key} is empty.')
                data = param.default
            out[key] = data
        return out

    def propagate(self, edge_index, size=None, **kwargs):
        r"""The initial call to start propagating messages.

        Args:
            adj (Tensor or SparseTensor): A :obj:`torch.LongTensor` or a
                :obj:`torch_sparse.SparseTensor` that defines the underlying
                message propagation.
                :obj:`edge_index` holds the indices of a general (sparse)
                assignment matrix of shape :obj:`[N, M]`.
                If :obj:`edge_index` is of type :obj:`torch.LongTensor`, its
                shape must be defined as :obj:`[2, num_messages]`, where
                messages from nodes in :obj:`edge_index[1]` are sent to
                nodes in :obj:`edge_index[0]`
                (in case :obj:`flow="source_to_target"`).
                If :obj:`edge_index` is of type
                :obj:`torch_sparse.SparseTensor`, its sparse indices
                :obj:`(row, col)` should relate to :obj:`row = edge_index[1]`
                and :obj:`col = edge_index[0]`.
            size (list or tuple, optional): The size :obj:`[N, M]` of the
                assignment matrix in case :obj:`edge_index` is a
                :obj:`LongTensor`.
                If set to :obj:`None`, the size will be automatically inferred
                and assumed to be quadratic.
                This argument is ignored in case :obj:`edge_index` is a
                :obj:`torch_sparse.SparseTensor`. (default: :obj:`None`)
            **kwargs: Any additional data which is needed to construct and
                aggregate messages, and to update node embeddings.
        """

        mp_type = self.__get_mp_type(edge_index)

        if mp_type == 'adj_t' and self.flow == 'target_to_source':
            raise ValueError(
                ('Flow direction "target_to_source" is invalid for message '
                 'propagation based on `torch_sparse.SparseTensor`. If you '
                 'really want to make use of a reverse message passing flow, '
                 'pass in the transposed sparse tensor to the message passing '
                 'module, e.g., `adj.t()`.'))

        if mp_type == 'edge_index':
            if size is None:
                size = [None, None]
            elif isinstance(size, int):
                size = [size, size]
            elif torch.is_tensor(size):
                size = size.tolist()
            elif isinstance(size, tuple):
                size = list(size)
        elif mp_type == 'adj_t':
            size = list(edge_index.sparse_sizes())[::-1]

        assert isinstance(size, list)
        assert len(size) == 2

        kwargs = self.__collect__(edge_index, size, kwargs)

        msg_kwargs = self.__distribute__(self.__msg_params__, kwargs)
        out = self.message(**msg_kwargs)

        aggr_kwargs = self.__distribute__(self.__aggr_params__, kwargs)
        out = self.aggregate(out, **aggr_kwargs)

        update_kwargs = self.__distribute__(self.__update_params__, kwargs)
        out = self.update(out, **update_kwargs)

        return out

    def message(self, x_j):
        r"""Constructs messages to node :math:`i` in analogy to
        :math:`\phi_{\mathbf{\Theta}}` for each edge in
        :math:`(j,i) \in \mathcal{E}` if :obj:`flow="source_to_target"` and
        :math:`(i,j) \in \mathcal{E}` if :obj:`flow="target_to_source"`.
        Can take any argument which was initially passed to :meth:`propagate`.
        In addition, tensors passed to :meth:`propagate` can be mapped to the
        respective nodes :math:`i` and :math:`j` by appending :obj:`_i` or
        :obj:`_j` to the variable name, *.e.g.* :obj:`x_i` and :obj:`x_j`.
        """

        return x_j

    def aggregate(self, inputs, index, dim_size=None):
        r"""Aggregates messages from neighbors as
        :math:`\square_{j \in \mathcal{N}(i)}`.

        By default, delegates call to scatter functions that support
        "add", "mean" and "max" operations specified in :meth:`__init__` by
        the :obj:`aggr` argument.
        """

        return scatter(inputs, index, dim=self.node_dim, dim_size=dim_size,
                       reduce=self.aggr)

    def update(self, inputs):
        r"""Updates node embeddings in analogy to
        :math:`\gamma_{\mathbf{\Theta}}` for each node
        :math:`i \in \mathcal{V}`.
        Takes in the output of aggregation as first argument and any argument
        which was initially passed to :meth:`propagate`.
        """

        return inputs
