#include <iostream>
#include <thread>
#include <vector>
#include <chrono>
#include <atomic>

void x86_task() {
    volatile unsigned int a = 1, b = 2, c = 3, d = 4;
    volatile unsigned int result = 0;

    float x = 1.23f, y = 4.56f, z = 7.89f;
    volatile float f_result = 0.0f;

    const int ARRAY_SIZE = 1024 * 1024;  // メモリアクセス用の配列サイズ
    volatile int* array = new int[ARRAY_SIZE];

    while (true) {
        // ループ内で整数演算を行う
        for (volatile int i = 0; i < 1000000; ++i) {
            result += a * b;                // 整数乗算
            result -= c;                    // 減算
            result ^= d;                    // XOR演算
            result = (result << 3) | (result >> 29); // ビットシフト

            if (result == 0) {
                result = a + b + c + d;     // リセット
            }
        }

        // 浮動小数点演算を行う
        for (volatile int i = 0; i < 1000000; ++i) {
            f_result = x * y;               // 浮動小数点乗算
            f_result += z;                  // 浮動小数点加算
            f_result /= y;                  // 浮動小数点除算

            if (f_result > 100.0f) {
                f_result = x + y + z;       // リセット
            }
        }

        // メモリアクセスの負荷
        for (int i = 0; i < ARRAY_SIZE; ++i) {
            array[i] = i * 2;               // 配列への書き込み
        }
        for (int i = 0; i < ARRAY_SIZE; ++i) {
            array[i] += array[(i + 1) % ARRAY_SIZE]; // 配列の読み込みと加算
        }

        // CPU負荷を軽減するために短いスリープを入れる（負荷を調整するため）
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    delete[] array;  // メモリの解放
}

int main(int argc, char* argv[]) {
    int num_threads = std::thread::hardware_concurrency(); // 利用可能なスレッド数を取得

    if (argc > 1) {
        num_threads = std::stoi(argv[1]); // 引数でスレッド数を指定可能
    }

    std::vector<std::thread> threads;
    for (int i = 0; i < num_threads; ++i) {
        // すべてのスレッドでx86の負荷をかける
        threads.emplace_back(x86_task);
    }

    // 負荷をかけ続ける
    for (auto& thread : threads) {
        thread.join();
    }

    return 0;
}
