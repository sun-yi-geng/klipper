import serial
import time
import logging
import os
from . import bus
import requests
import json
from logging.handlers import RotatingFileHandler
# 设置日志记录
class CountingRotatingFileHandler(RotatingFileHandler):
    def __init__(self, filename, max_lines=100, backupCount=0, encoding=None, delay=False):
        self.max_lines = max_lines
        super().__init__(filename, maxBytes=0, backupCount=backupCount, encoding=encoding, delay=delay)

    def emit(self, record):
        try:
            if not os.path.exists(self.baseFilename):
                with open(self.baseFilename, 'w') as f:
                    pass
            with open(self.baseFilename, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            if len(lines) >= self.max_lines:
                with open(self.baseFilename, 'w', encoding='utf-8') as f:
                    f.truncate()  # 清空文件
        except (IOError, FileNotFoundError, OSError):
            pass
        super().emit(record)

# 设置日志记录
main_log = logging.getLogger('main_log')
main_log.setLevel(logging.DEBUG)

log_file_path = '/home/pi/klipper/log/main.log'
handler = CountingRotatingFileHandler(log_file_path, max_lines=1500)
handler.setLevel(logging.DEBUG)

main_formatter = logging.Formatter('%(asctime)s - %(levelname)s - [Main] %(message)s')
handler.setFormatter(main_formatter)
main_log.addHandler(handler)

def send_to_klipper(variable_name, value, api_key=None, host="localhost", port=7125):
        url = f"http://{host}:{port}/printer/gcode/script"
        command = f"SET_GCODE_VARIABLE MACRO=CESHII VARIABLE=zoffset VALUE={value}"
        payload = {"script": command}
        headers = {"X-Api-Key": api_key} if api_key else None
        
        try:
            main_log.debug(f"{payload}")
            response = requests.post(url,  json=payload, headers=headers, timeout=1)
            response.raise_for_status() 
            
            print(f"变量 {variable_name} 已更新为 {value}")
        except requests.exceptions.RequestException  as e:
            print(f"错误：{e}")

z_name = 'zoffset'

class USBCommunicator:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        
        # 注册G-code命令
        self.gcode.register_command('RUN_USB_SCRIPT', self.handle_run_usb_script)
        
        # 串口配置
        self.ser = self.init_serial()

    def init_serial(self):
        """初始化串口连接"""
        for i in range(5):  # 尝试5次
            try:
                ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)
                if ser.is_open:
                    main_log.debug("串口初始化成功")
                    return ser
            except serial.SerialException as e:
                main_log.error(f"串口初始化失败，第{i + 1}次重试... {e}")
                time.sleep(2)
        raise Exception("串口初始化失败")

    def read_heartbeat(self):
        """发送指令并等待回复"""
        SEND_COMMAND = bytes([0xA5, 0xA5, 0xA5, 0xA5])
        RECEIVE_COMMAND = bytes([0xA5, 0xA5, 0xA5, 0xA5])
        DETECTION_DURATION = 5  # 接收等待时间
        TEMP_FILE_PATH = 'receive_data.txt'

        self.ser.write(SEND_COMMAND)  # 发送指令
        
        #main_log.debug("读取数据成功。")
        detection_start_time = time.time()
        detection_data = []  # 存储每次收到的数据

        a5_count = 0
        a5_detected = True

        while time.time() - detection_start_time < DETECTION_DURATION:
            data = self.ser.read(1)  # 每次读取2个字节
            if data:  # 如果有数据可用
                if data == bytes([0xA5]):  # 如果读取到00A5
                    a5_count += 1
                    main_log.debug(f"第{a5_count}次")
                    if a5_count == 4:  # 当连续读取到4个A5时
                        if a5_detected:  # 如果已经检测到过一次连续的A5
                            
                            main_log.info("开始读取串口数据...")
                            
                            data = self.ser.read(3)
                            if data:  # 如果有数据可用
                                main_log.debug(f"串口接受为{data}")
                                # 转换为十进制
                               # 合并两个字节为一个 16 位无符号整型数值（大端）
                                value = int.from_bytes(data, byteorder='big')
                                # 转换为浮点数并保留两位小数
                                z_offset = round(value / 100, 2)
                                detection_data.append(z_offset)
                                main_log.info("存储")
                                main_log.debug(f"shuju:{detection_data}")
                                
                        else:
                            a5_detected = True  # 标记检测到第二次连续的A5
                else:
                    a5_count = 0  # 重置A5计数器

        # 保存数据到临时文件
        with open(TEMP_FILE_PATH, 'w') as f:
            for d in detection_data:
                # f.write(','.join(f"{val:.2f}" for val in d) + '\n')  #二维列表的存储方式
                f.write(f"{d:.2f}\n")
        send_to_klipper(variable_name=z_name, value=z_offset, api_key=None, host="localhost", port=7125)
        main_log.info(f"zoffset:{z_offset},gcode runned!")
        
    def handle_run_usb_script(self, gcmd):
        """G-code command to trigger readheartbeat and save data."""
        try:
            self.read_heartbeat()  # 执行串口通信逻辑
            gcmd.respond_info(f"USB script executed successfully")
        except Exception as e:
            gcmd.respond_info(f"Error executing USB script: {str(e)}")

def load_config(config):
    return USBCommunicator(config)

