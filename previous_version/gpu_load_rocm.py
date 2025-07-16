#!/usr/bin/env python3
"""
gpu_load_rocm.py
----------------
ROCm環境向けのGPU負荷テストモジュールです。
3D描画（OpenGL/pygame）とGPGPU（PyTorchのテンソル計算）による負荷を提供します。
メインプログラム（gpu_load.py）から同一のAPI名で呼び出されます。

※ 3D描画はウィンドウ表示を行わずにGPUへの描画命令を発行し、
    ログで進捗を出力するのみです。ウィンドウはオフスクリーンに配置されます。
"""

import os
import time
import threading
import torch

# ROCm用環境変数の設定（必要に応じて）
os.environ["AMD_SERIALIZE_KERNEL"] = "1"   # 正しい値は 0 または 1
os.environ["TORCH_USE_HIP_DSA"] = "1"

# Mesaドライバのパスをシステム側のディレクトリに変更（環境に合わせて調整してください）
os.environ["LIBGL_DRIVERS_PATH"] = "/usr/lib/x86_64-linux-gnu/dri"
# 必要に応じてLD_LIBRARY_PATHも設定
os.environ["LD_LIBRARY_PATH"] = "/usr/lib:/usr/lib64:" + os.environ.get("LD_LIBRARY_PATH", "")

#############################
# (1) GPGPU 負荷（テンソル計算）
#############################
def tensor_calculation(load_percentage, stop_event, gpu_id):
    torch.cuda.set_device(gpu_id)
    tensor_size = 8000  # 初期テンソルサイズ（正方行列の辺の長さ）
    min_size = 100      # 最小サイズ
    while not stop_event.is_set():
        try:
            a = torch.rand((tensor_size, tensor_size), device='cuda')
            b = torch.rand((tensor_size, tensor_size), device='cuda')
            _ = torch.matmul(a, b)
            torch.cuda.synchronize()
        except RuntimeError as e:
            error_message = str(e)
            # "invalid device function" エラーはログ出力を抑制し、サイズを縮小
            if "invalid device function" in error_message:
                if tensor_size > min_size:
                    tensor_size = max(tensor_size - 500, min_size)
                time.sleep(0.5)
                continue
            else:
                print(f"[ROCm][ERROR] Tensor calculation error on GPU {gpu_id} with size {tensor_size}: {e}")
                new_size = max(tensor_size - 500, min_size)
                if new_size < tensor_size:
                    tensor_size = new_size
                    print(f"[ROCm][INFO] Reducing tensor size to {tensor_size} on GPU {gpu_id}")
                else:
                    time.sleep(0.5)
                continue
        # 正常に計算できた場合、徐々にサイズを戻す（急激な増加は避ける）
        if tensor_size < 8000:
            tensor_size = min(tensor_size + 100, 8000)
        time.sleep(1 / (load_percentage + 1))

def apply_gpu_tensor_load_func(load_percentage, stop_event, gpu_ids):
    print(f"[ROCm] Starting GPU Tensor Load with {load_percentage}% on GPUs: {gpu_ids}")
    for gpu_id in gpu_ids:
        threading.Thread(
            target=tensor_calculation,
            args=(load_percentage, stop_event, gpu_id),
            daemon=True
        ).start()

#############################
# (2) 3D描画によるGPU負荷（OpenGL/pygame）
#############################
try:
    import pygame
    from pygame.locals import *
    from OpenGL.GL import *
    from OpenGL.GLU import *
except ImportError:
    pygame = None

def initialize_lighting():
    glEnable(GL_LIGHTING)
    glEnable(GL_LIGHT0)
    light_position = [10.0, 10.0, 10.0, 1.0]
    glLightfv(GL_LIGHT0, GL_POSITION, light_position)
    glLightfv(GL_LIGHT0, GL_DIFFUSE, [1.0, 1.0, 1.0, 1.0])
    glEnable(GL_COLOR_MATERIAL)

def draw_cube():
    vertices = [
        (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
        (-1, -1, 1),  (1, -1, 1),  (1, 1, 1),  (-1, 1, 1)
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (2, 3, 7, 6),
        (1, 2, 6, 5),
        (0, 3, 7, 4)
    ]
    glBegin(GL_QUADS)
    for face in faces:
        for vertex in face:
            glVertex3fv(vertices[vertex])
    glEnd()

def render_gpu_load(load_percentage, stop_event, gpu_id):
    if pygame is None:
        print("[ROCm][ERROR] pygame or PyOpenGL is not available. Skipping 3D load.")
        return

    # ウィンドウ表示を隠すため、ウィンドウ位置をオフスクリーンに設定
    os.environ["SDL_VIDEO_WINDOW_POS"] = "10000,10000"

    try:
        pygame.init()
        # OpenGL コンテキスト属性の設定
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 2)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 1)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_COMPATIBILITY)
        screen = pygame.display.set_mode((800, 600), DOUBLEBUF | OPENGL)
        pygame.display.set_caption(f"[ROCm] GPU 3D Load Test (GPU {gpu_id})")
    except Exception as e:
        print(f"[ROCm][ERROR] Failed to initialize pygame/OpenGL: {e}")
        return

    try:
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45, (800 / 600), 0.1, 50.0)
        glMatrixMode(GL_MODELVIEW)
        glEnable(GL_DEPTH_TEST)
        initialize_lighting()
        glClearColor(0.2, 0.2, 0.2, 1.0)
    except Exception as e:
        print(f"[ROCm][ERROR] OpenGL initialization failed: {e}")
        pygame.quit()
        return

    rotation_angle = 0.0
    clock = pygame.time.Clock()
    frame_count = 0
    while not stop_event.is_set():
        for event in pygame.event.get():
            if event.type == QUIT:
                stop_event.set()
        try:
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glLoadIdentity()
            gluLookAt(0, 0, 10, 0, 0, 0, 0, 1, 0)
            glRotatef(rotation_angle, 1, 1, 0)
            draw_cube()
        except Exception as e:
            print(f"[ROCm][ERROR] OpenGL drawing error: {e}")
            break

        glFinish()  # GPUに描画命令を確実に送る
        clock.tick(60)
        frame_count += 1
        if frame_count % 60 == 0:
            print(f"[ROCm][INFO] GPU 3D load test on GPU {gpu_id}: {frame_count} frames rendered.")
        rotation_angle += load_percentage * 0.1
    pygame.quit()
    print(f"[ROCm][INFO] Exiting GPU 3D load test on GPU {gpu_id}.")

#############################
# (3) 複合負荷（テンソル計算＋3D描画）
#############################
def apply_combined_load_func(load_percentage, stop_event, gpu_ids):
    for gpu_id in gpu_ids:
        threading.Thread(
            target=tensor_calculation,
            args=(load_percentage, stop_event, gpu_id),
            daemon=True
        ).start()
        threading.Thread(
            target=render_gpu_load,
            args=(load_percentage, stop_event, gpu_id),
            daemon=True
        ).start()

#############################
# (4) VRAM負荷テスト
#############################
def allocate_vram_dynamic(vram_percentage, stop_event, gpu_id):
    device = torch.device(f'cuda:{gpu_id}')
    print(f"[ROCm] Starting VRAM load on GPU {gpu_id} => target={vram_percentage}% of total memory.")
    allocated_tensors = []
    while not stop_event.is_set():
        free_mem, total_mem = torch.cuda.mem_get_info(device=device)
        used_mem = total_mem - free_mem
        target_bytes = int(total_mem * (vram_percentage / 100.0))
        if used_mem < target_bytes:
            to_allocate = target_bytes - used_mem
            chunk_size = max(to_allocate // 10, 1)
            chunk_size_float = max(chunk_size // 4, 1)
            try:
                tensor = torch.zeros(chunk_size_float, dtype=torch.float32, device=device)
                allocated_tensors.append(tensor)
            except RuntimeError as e:
                error_message = str(e)
                if "invalid device function" in error_message:
                    time.sleep(1.0)
                    continue
                else:
                    print(f"[ROCm][WARN] OOM on GPU {gpu_id}: {e}")
                    time.sleep(1.0)
            time.sleep(0.1)
        elif used_mem > target_bytes:
            to_free = used_mem - target_bytes
            freed = 0
            while freed < to_free and allocated_tensors:
                pop_tensor = allocated_tensors.pop()
                freed += pop_tensor.numel() * 4
                del pop_tensor
            torch.cuda.empty_cache()
            time.sleep(0.1)
        else:
            time.sleep(0.2)
    print(f"[ROCm][INFO] Stopping VRAM load on GPU {gpu_id}. Freed all allocated tensors.")
    del allocated_tensors
    torch.cuda.empty_cache()
    print(f"[ROCm][INFO] GPU {gpu_id} memory freed.")

def apply_gpu_vram_load_func(vram_percentage, stop_event, gpu_ids):
    for gpu_id in gpu_ids:
        threading.Thread(
            target=allocate_vram_dynamic,
            args=(vram_percentage, stop_event, gpu_id),
            daemon=True
        ).start()

#########################################
# エクスポートする関数名（main.pyから同一のAPI名で呼び出し）
#########################################
apply_gpu_tensor_load_func = apply_gpu_tensor_load_func if 'apply_gpu_tensor_load_func' in globals() else apply_gpu_tensor_load_func
apply_combined_load_func = apply_combined_load_func if 'apply_combined_load_func' in globals() else apply_combined_load_func
apply_gpu_vram_load_func = apply_gpu_vram_load_func if 'apply_gpu_vram_load_func' in globals() else apply_gpu_vram_load_func
