import torch

if hasattr(torch.version, 'hip') and torch.version.hip is not None:
    print("Detected GPU platform: ROCm")
    # 絶対インポート：パッケージ名 "gpu_load" を付与する
    from gpu_load.gpu_load_rocm import (
        apply_gpu_tensor_load_func as apply_gpu_tensor_load,
        apply_combined_load_func as apply_combined_load,
        apply_gpu_vram_load_func as apply_gpu_vram_load
    )
elif torch.version.cuda is not None:
    print("Detected GPU platform: CUDA")
    from gpu_load.gpu_load_cuda import (
        apply_gpu_tensor_load_func as apply_gpu_tensor_load,
        apply_combined_load_func as apply_combined_load,
        apply_gpu_vram_load_func as apply_gpu_vram_load
    )
else:
    raise RuntimeError("No supported GPU platform found.")
