from .debug import is_debug_enabled, debug, set_debug
import torch_geometric.nn
import torch_geometric.data
import torch_geometric.transforms
import torch_geometric.utils

# Lazy-load datasets to avoid loading unneeded dependencies
from torch_geometric.utils.lazy_loader import LazyLoader
datasets = LazyLoader("datasets", globals(), "torch_geometric.datasets")

__version__ = '1.6.3'

__all__ = [
    'is_debug_enabled',
    'debug',
    'set_debug',
    'torch_geometric',
    '__version__',
]
