# 主线程继续执行其他任务
# 测试多线程下同时两套死循环的运行
#-----------新线程t1代码的开始----------------
import threading

def print_numbers(arg1, arg2):
    while 1:
        print(arg1+arg2)

# 创建线程
t1 = threading.Thread(target=print_numbers, args=("111","222"))

# 启动线程
t1.start()
#-----------新线程t1代码的结束----------------

# 主线程继续执行其他任务
while 1:
    print("我进死循环了，如果不加多线程，其他人是没法执行的")