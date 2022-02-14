import os 
import sys
import time 
import struct
import threading

from tqdm import trange
from ethernet_provider import Ethernet_Dev
from upgrade_driver import UpgradeDriver

PART_NAME = ['rtk', 'ins', 'sdk', 'imu']

class Executor:
    def __init__(self):
        self.driver = UpgradeDriver()
        self.ether = Ethernet_Dev()
        self.is_stop = False
        self.flag_list = []
        self.fw_part_lens_list = []
        self.fw_part_list = []
        
    def upgrade_work(self):
        self.driver.sniff_dev()
        self.driver.get_dev_info()
        '''TODO
        parse the response to get info
        '''
        content = self.driver.setup()
        content_len = len(content)

        rtk_start_flag = content.find(b'rtk_start:')
        ins_start_flag = content.find(b'ins_start:')
        sdk_start_flag = content.find(b'sdk_start:')
        imu_start_flag = content.find(b'imu_start:')
        self.flag_list = [rtk_start_flag, ins_start_flag, sdk_start_flag, imu_start_flag]

        rtk_data_lens = struct.unpack('<I', content[(rtk_start_flag+10):(rtk_start_flag+14)])[0]
        ins_data_lens = struct.unpack('<I', content[(ins_start_flag+10):(ins_start_flag+14)])[0] 
        sdk_data_lens = struct.unpack('<I', content[(sdk_start_flag+10):(sdk_start_flag+14)])[0]
        imu_data_lens = struct.unpack('<I', content[(imu_start_flag+10):(imu_start_flag+14)])[0]
        self.fw_part_lens_list = [rtk_data_lens, ins_data_lens, sdk_data_lens, imu_data_lens]

        rtk_bin_data = content[(rtk_start_flag+14):ins_start_flag]
        ins_bin_data = content[(ins_start_flag+14):sdk_start_flag]
        sdk_bin_data = content[(sdk_start_flag+14):imu_start_flag]
        imu_bin_data = content[(imu_start_flag+14):content_len]
        self.fw_part_list = [rtk_bin_data, ins_bin_data, sdk_bin_data, imu_bin_data]

        # a = self.driver.get_bin_info_list(len(sdk_bin_data), sdk_bin_data)

        pass_time = 0
        for i in range(len(self.fw_part_list)):
            data_lens = len(self.fw_part_list[i])
            if data_lens == self.fw_part_lens_list[i]:
                pass_time += 1
            else:
                failed_part = PART_NAME[i]
                print(f'Firmware validity check failed, failed on {failed_part}') 

        if pass_time != len(self.fw_part_list):
            print('Upgrade Failed')
            time.sleep(2)
            self.driver.kill_app(1, 2)

        # upgrade rtk/ins part of the device
        print('Upgrade strat...')
        self.driver.jump2boot(3)
        self.driver.shake_hand()
        print('rtk part upgrade start')
        self.rtk_part_upgrade(self.fw_part_list[0])
        time.sleep(0.5)
        print('ins part upgrade start')
        self.ins_part_upgrade(self.fw_part_list[1])
        time.sleep(0.5)
        self.driver.jump2app(2)   

        # upgrade sdk9100 part of the device
        self.driver.shake_hand() 
        self.driver.sdk_jump2boot(3)
        self.driver.shake_hand()
        print('sdk part upgrade start')
        self.sdk_part_upgrade(self.fw_part_list[2])
        self.driver.sdk_jump2app(3)
        print('sdk upgrade successed\n')
        
        # upgrade imu part of the device
        self.driver.shake_hand()  
        self.driver.imu_jump2boot(3)
        self.driver.shake_hand()
        print('imu part upgrade start')
        self.imu_part_upgrade(self.fw_part_list[3])
        self.driver.imu_jump2app(3)
        print('imu upgrade successed')

    def rtk_part_upgrade(self, content):
        core = '0'
        content_len = len(content)
        upgrade_flag = 0
        self.driver.before_write_content(core, content_len)

        step = 192
        current_side = self.flag_list[0]
        write_turns = int(content_len/step)
        
        for _ in trange(write_turns):
            target_content = content[current_side: (current_side+step)]
            time.sleep(0.01)
            self.driver.write_block(step, current_side, upgrade_flag, target_content)
            time.sleep(0.01)
            current_side += step
            upgrade_flag += 1
        
        extract_content_flag = content_len - (step * write_turns)
        extract_content = content[(content_len-extract_content_flag):content_len]
        upgrade_flag += 1

        self.driver.write_block(extract_content_flag, current_side, upgrade_flag, extract_content)
        print('rtk upgrade successed\n')

    def ins_part_upgrade(self, content):
        core = '1'
        content_len = len(content)
        upgrade_flag = 0
        self.driver.before_write_content(core, content_len)

        step = 192
        copy_side = 0 # just a fake side to cut content
        current_side = self.flag_list[1] # current_side is an actual side of bin and it will correspond to copy_side
        write_turns = int(content_len/step)
        
        for _ in trange(write_turns):
            target_content = content[copy_side: (copy_side+step)]
            time.sleep(0.01)
            self.driver.write_block(step, copy_side, upgrade_flag, target_content)
            time.sleep(0.01)
            copy_side += step
            current_side += step
            upgrade_flag += 1
        
        extract_content_flag = content_len - (step * write_turns)
        extract_content = content[copy_side:(copy_side+extract_content_flag)]
        upgrade_flag += 1

        self.driver.write_block(extract_content_flag, copy_side, upgrade_flag, extract_content)
        print('ins upgrade successed\n')

    def imu_part_upgrade(self, content):
        content_len = len(content)
        step = 192
        copy_side = 0 # just a fake side to cut content
        current_side = self.flag_list[3] # current_side is an actual side of bin and it will correspond to copy_side
        write_turns = int(content_len/step)

        for i in trange(write_turns):
            target_content = content[copy_side:(copy_side+step)]
            self.driver.imu_write_block(step, copy_side, target_content, i)
            copy_side += step
            current_side += step

        extract_content_flag = content_len - (step * write_turns)
        extract_content = content[copy_side:(copy_side+extract_content_flag)]
        self.driver.imu_write_block(extract_content_flag, copy_side, extract_content, i)

    def sdk_part_upgrade(self, content):
        content_len = len(content)
        bin_info_list = self.driver.get_bin_info_list(content_len, content)
        if self.driver.sdk_sync() == False:
            print('sdk sync failed')
            self.driver.kill_app(1, 2)
        self.driver.flash_write_pre(content)
        time.sleep(0.1)
        if self.driver.change_buad() == False:
            print('Prepare baudrate change command failed\n')
            self.driver.kill_app(1, 2)
        if self.driver.send_baud(230400) == False:
            print('Send baudrate command failed\n')
            self.driver.kill_app(1, 2)
        if self.driver.baud_check() == False:
            print('Baudrate check failed\n')
            self.driver.kill_app(1, 2)
        if self.driver.is_host_ready() == False:
            print('Host is not ready.\n')
            self.driver.kill_app(1, 2)
        if self.driver.send_boot() == False:
            print('SDK boot failed\n')
            self.driver.kill_app(1, 2)
        if self.driver.send_write_flash() == False:
            print('Prepare flash change command failed\n')
            self.driver.kill_app(1, 2)
        if self.driver.send_bin_info(bin_info_list) == False:
            print('Send binary info failed')
            self.driver.kill_app(1, 2)
        for i in range(2):
            result = self.driver.wait()
            if i == 0 and result == False:
                print('Wait devinit failed')
            elif i == 1 and result == False:
                print('Wait erase failed')

        if self.driver.flash_write(content_len, content) == False:
            print('Write app bin failed')
            self.driver.kill_app(1, 2)

        for i in range(3):
            time.sleep(1)
            result = self.driver.flash_crc()
            if not result and i == 2:
                print('CRC check fail')
            else:
                break

a = Executor()
a.upgrade_work()
    