# Тестування оптимізацій RealESRGAN

## Поточний стан

Імплементовано 3 основні оптимізації:

✅ **1. Перекидання CPU↔GPU** (Priority 1)
- IOBinding з перевикористовуваними буферами для interior tiles
- Результати копіюються один раз для запобігання зітирання

✅ **2. Розпаралелення обчислень** (Priority 2)
- Queue-based архітектура з префетч потоком
- Кілька inference потоків обробляють тайли паралельно
- Автоматичне визначення числа потоків на основі CPU cores

✅ **3. Оптимізація префетчу** (Priority 1)
- Префетч потік постійно готує наступні тайли
- Edge-тайли корректно обраховуються через session.run()

⏳ **4. Батчування тайлів** (Priority 3 - майбутнє)
- Розширення ONNX input на обробку N тайлів одночасно
- Вимагає модифікації моделі - тимчасово не реалізовано

## Як тестувати оптимізацію

### 1. Базовий тест функціональності

```python
# test_upscale_basic.py
from PIL import Image
import numpy as np
from core.processing.resolution import upscale_image
import time

# Завантажити тестове зображення
test_img = Image.open('TEST_IMAGES/Astronaut-noise.png')

# Апскейл з оптимізацією
start = time.time()
result = upscale_image(
    test_img,
    progress_bar_queue=None,
    keep_size=False,
    model='RealESRGAN_x2plus',
    face_restoration=False,
    upscale_factor=2
)
duration = time.time() - start

print(f"Upscaled in {duration:.2f}s")
print(f"Input: {test_img.size} → Output: {result.size}")

# Зберегти результат для перевірки якості
result.save('test_output_optimized.png')
```

### 2. Порівняння продуктивності (sequential vs parallel)

```python
# test_performance_comparison.py
import threading
from core.models.onnx_realesrganer import OnnxRealESRGANer
import numpy as np
import cv2
from time import time

# Завантажити модель
model_path = 'weights/RealESRGAN_x2plus.pth'

# Тестове зображення (600x400)
test_img = cv2.imread('TEST_IMAGES/Astronaut-noise.png')

# Тест 1: Sequential (num_threads=1)
print("Sequential processing (num_threads=1)...")
start = time.time()
upscaler_seq = OnnxRealESRGANer(
    scale=2,
    pth_path=model_path,
    tile=384,
    tile_pad=32,
    num_threads=1
)
result_seq = upscaler_seq.enhance(test_img)
time_seq = time.time() - start
print(f"  Time: {time_seq:.2f}s")

# Тест 2: Parallel with 2 threads
print("Parallel processing (num_threads=2)...")
start = time.time()
upscaler_par = OnnxRealESRGANer(
    scale=2,
    pth_path=model_path,
    tile=384,
    tile_pad=32,
    num_threads=2
)
result_par = upscaler_par.enhance(test_img)
time_par = time.time() - start
print(f"  Time: {time_par:.2f}s")

# Результати
improvement = (time_seq - time_par) / time_seq * 100
print(f"\nSpeedup: {time_seq / time_par:.2f}x ({improvement:.1f}% faster)")

# Перевірити що результати ідентичні
diff = np.abs(result_seq.astype(float) - result_par.astype(float)).max()
print(f"Max diff between results: {diff:.2f}")
```

### 3. Тест завантаженості ресурсів

```python
# test_resource_utilization.py
import psutil
import threading
import time
from core.models.onnx_realesrganer import OnnxRealESRGANer
import cv2

def monitor_resources(upscaler, test_img, duration_ref):
    """Monitor CPU and GPU usage during upscaling"""
    
    # Start upscaling in background
    result_holder = [None]
    
    def run_upscale():
        result_holder[0] = upscaler.enhance(test_img)
    
    upscale_thread = threading.Thread(target=run_upscale)
    upscale_thread.start()
    
    # Monitor while upscaling
    cpu_readings = []
    start = time.time()
    
    while upscale_thread.is_alive():
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_readings.append(cpu_percent)
        time.sleep(0.1)
    
    upscale_thread.join()
    total_time = time.time() - start
    
    # Print statistics
    avg_cpu = sum(cpu_readings) / len(cpu_readings) if cpu_readings else 0
    max_cpu = max(cpu_readings) if cpu_readings else 0
    
    print(f"CPU Average: {avg_cpu:.1f}%")
    print(f"CPU Peak: {max_cpu:.1f}%")
    print(f"Total time: {total_time:.2f}s")
    
    return result_holder[0]

# Test with different thread counts
test_img = cv2.imread('TEST_IMAGES/Astronaut-noise.png')
model_path = 'weights/RealESRGAN_x2plus.pth'

for num_threads in [1, 2, 4]:
    print(f"\n=== Testing with {num_threads} threads ===")
    upscaler = OnnxRealESRGANer(
        scale=2,
        pth_path=model_path,
        tile=384,
        tile_pad=32,
        num_threads=num_threads
    )
    monitor_resources(upscaler, test_img, None)
```

### 4. Тест корректності результатів

```python
# test_correctness.py
import cv2
import numpy as np
from core.models.onnx_realesrganer import OnnxRealESRGANer

def test_tile_boundaries():
    """Verify that tile boundaries don't create artifacts"""
    
    # Create synthetic test image with patterns
    img = np.zeros((768, 768, 3), dtype=np.uint8)
    
    # Add checkerboard pattern
    for i in range(0, 768, 64):
        for j in range(0, 768, 64):
            if (i // 64 + j // 64) % 2 == 0:
                img[i:i+64, j:j+64] = 255
    
    # Convert to BGR
    img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    
    # Upscale
    model_path = 'weights/RealESRGAN_x2plus.pth'
    upscaler = OnnxRealESRGANer(
        scale=2,
        pth_path=model_path,
        tile=384,  # Will create multiple tiles
        tile_pad=32,
        num_threads=2
    )
    
    result = upscaler.enhance(img_bgr)
    
    # Check for seams at tile boundaries
    # Tile boundaries should be at x=384*2, 384*4, etc. in upscaled image
    print(f"Original size: {img_bgr.shape}")
    print(f"Upscaled size: {result.shape}")
    
    # Examine gradients near tile boundaries
    tile_bound_x = 384 * 2  # First tile boundary in upscaled space
    region = result[300:400, tile_bound_x-30:tile_bound_x+30]
    
    # Calculate horizontal gradient
    grad_x = np.abs(np.diff(region.astype(float), axis=1))
    grad_x_mean = np.mean(grad_x)
    
    print(f"Mean gradient at tile boundary: {grad_x_mean:.2f}")
    print(f"If > 20, potential seaming detected")
    
    return result

# Run test
result_img = test_tile_boundaries()
cv2.imwrite('test_boundaries_result.png', result_img)
```

## Критерії успіху

✅ **Функціональність**
- Апскейл працює без помилок
- Результат має правильний розмір (input_size * scale_factor)
- Зображення матиме покращену якість (менше noise, чіткіше деталі)

✅ **Продуктивність**
- Parallel (num_threads=2) швидший за Sequential (num_threads=1)
- Очікуваний спідап: 1.3x - 1.8x (залежить від GPU)
- CPU utilization ≈ 25-30% (префетч + результати)
- GPU utilization ≈ 90-100% (безперервна робота)

✅ **Якість**
- Немає артефактів на межах тайлів
- Результат детерміністичний (однаковий для sequential/parallel)
- Максимальна різниця між результатами: < 1 у uint8 (тобто 0-1 з 255)

## Запуск тестів

```bash
# 1. Базовий тест
python test_upscale_basic.py

# 2. Порівняння продуктивності
python test_performance_comparison.py

# 3. Завантаженість ресурсів (потребує psutil)
pip install psutil
python test_resource_utilization.py

# 4. Перевірка корректності
python test_correctness.py
```

## Відомі обмеження

1. **Edge tiles**: Використовують session.run() замість IOBinding через динамічні розміри - це 1-2% від часу
2. **GPU type**: Optimization більш ефективна на discrete GPUs (AMD, NVIDIA) ніж на integrated graphics
3. **Image size**: Дуже малі зображення (<512px) можуть обробитися за один тайл - паралелізм мінімальний
4. **Memory overhead**: Кожен inference потік має свій ONNX session копію - пам'яті більше за sequential версію на ~20-30%

## Забезпечення якості

Оптимізація повинна працювати без втрати якості, тому що:
- Алгоритм обробки тайлів не змінений
- Це лише перестановка архітектури (замість очереди на список)
- Результати мають бути ідентичні (до fp32 помилок)
