from typing import Optional

from torch import Tensor
from torch_scatter import scatter, segment_csr, gather_csr

from .num_nodes import maybe_num_nodes


def softmax(src: Tensor, index: Tensor, ptr: Optional[Tensor] = None,
            num_nodes: Optional[int] = None) -> Tensor:
    r"""Computes a sparsely evaluated softmax.
    Given a value tensor :attr:`src`, this function first groups the values
    along the first dimension based on the indices specified in :attr:`index`,
    and then proceeds to compute the softmax individually for each group.

    Args:
        src (Tensor): The source tensor.
        index (LongTensor): The indices of elements for applying the softmax.
        num_nodes (int, optional): The number of nodes, *i.e.*
            :obj:`max_val + 1` of :attr:`index`. (default: :obj:`None`)

    :rtype: :class:`Tensor`
    """

    if ptr is None:
        N = maybe_num_nodes(index, num_nodes)
        out = scatter(src, index, dim=0, dim_size=N, reduce='max')[index]
        out = out.exp()
        out_sum = scatter(out, index, dim=0, dim_size=N, reduce='sum')
        out = out / (out_sum[index] + 1e-16)
        return out
    else:
        out = gather_csr(segment_csr(src, ptr, reduce='max'), ptr)
        out = out.exp()
        out_sum = segment_csr(out, ptr, reduce='sum')
        out = out / (gather_csr(out_sum, ptr) + 1e-16)
        return out
