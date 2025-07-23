import serial
import numpy as np
from dataclasses import dataclass
from collections import deque
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class STM_Status:
    bias: int = 0
    dac_z: int = 0
    dac_x: int = 0
    dac_y: int = 0
    adc: int = 0
    steps: int = 0
    is_approaching: bool = False
    is_const_current: bool = False
    is_scanning: bool = False
    time_millis: int = 0

    @staticmethod
    def from_list(values):
        return STM_Status(bias=values[0],
                          dac_z=values[1],
                          dac_x=values[2],
                          dac_y=values[3],
                          adc=values[4],
                          steps=values[5],
                          is_approaching=bool(values[6]),
                          is_const_current=bool(values[7]),
                          is_scanning=bool(values[8]),
                          time_millis=values[9])

    @staticmethod
    def adc_to_amp(adc: int):
        return 1.0 * adc / 32768 * 10.24 / 100e6

    @staticmethod
    def dac_to_dacz_volts(dac: int):
        return 1.0 * (dac - 32768) / 32768 * 10.0 / 2.0

    @staticmethod
    def dac_to_dacx_volts(dac: int):
        return 1.0 * (dac - 32768) / 32768 * 10.0 / 2.0

    @staticmethod
    def dac_to_dacy_volts(dac: int):
        return 1.0 * (dac - 32768) / 32768 * 10.0 / 2.0

    @staticmethod
    def dac_to_bias_volts(dac: int):
        return 1.0 * (dac - 32768) / 32768 * 3.0

    def to_string(self):
        return f"""STM Status:
Bias: {self.bias} ({self.dac_to_bias_volts(self.bias):.3f}V)
Z: {self.dac_z} ({self.dac_to_dacz_volts(self.dac_z):.3f}V)
X: {self.dac_x} ({self.dac_to_dacx_volts(self.dac_x):.3f}V)
Y: {self.dac_y} ({self.dac_to_dacy_volts(self.dac_y):.3f}V)
ADC: {self.adc} ({self.adc_to_amp(self.adc):.3e}A)
STEPS: {self.steps}
Approaching: {self.is_approaching}
ConstCurrent: {self.is_const_current}
Scan: {self.is_scanning}
Time: {self.time_millis}"""


class STM(object):
    def __init__(self, device=None):
        self.is_opened = False
        self.busy = False
        if device:
            self.open(device)

        self.status = STM_Status()
        self.hist_length = 1000
        self.history = deque(maxlen=self.hist_length)
        self.scan_adc = None
        self.scan_dacz = None
        self.scan_config = [0, 100, 10, 0, 100, 10]
        self.scan_adc = np.ones([512, 512], dtype=np.float32)
        self.scan_dacz = np.ones([512, 512], dtype=np.float32)
        self.target_current = 1e-9  # Default target current (1nA)

    def open(self, device):
        try:
            self.stm_serial = serial.Serial(device, 115200, timeout=1)
            self.stm_serial.set_buffer_size(rx_size=128000, tx_size=128000)
            self.is_opened = True
            logger.info(f"Successfully opened connection to {device}")
        except Exception as e:
            logger.error(f"Failed to open serial connection: {e}")
            raise

    def get_status(self):
        if self.busy:
            return self.history[-1] if self.history else self.status

        if not self.is_opened:
            self.status = STM_Status()
            return self.status

        try:
            self.send_cmd('GSTS')
            status_str = self.stm_serial.readline().decode().strip()
            if status_str:
                status_value = status_str.split(',')
                if len(status_value) >= 10:
                    status_value = [int(x) for x in status_value]
                    self.status = STM_Status.from_list(status_value)
        except Exception as e:
            logger.warning(f"Error getting status: {e}")
            return self.history[-1] if self.history else self.status

        self.history.append(self.status)
        return self.status

    def reset(self):
        self.send_cmd('RSET')
        self.clear()

    def clear(self):
        self.history.clear()

    def send_cmd(self, cmd):
        if self.is_opened and not self.busy:
            try:
                self.stm_serial.write((cmd + '\n').encode())
            except Exception as e:
                logger.error(f"Error sending command {cmd}: {e}")

    def move_motor(self, steps):
        self.send_cmd(f'MTMV {steps}')

    def approach(self, target_dac, steps):
        if self.busy:
            return

        self.busy = True
        try:
            # Initial approach
            self.send_cmd(f'APRH {target_dac} {steps}')
        finally:
            self.busy = False

    def stop(self):
        self.send_cmd('STOP')
        self.busy = False

    def measure_iv_curve(self, dac_start, dac_end, dac_step):
        self.busy = True
        try:
            self.send_cmd(f'IVME {dac_start} {dac_end} {dac_step}')
            time.sleep(0.1 * abs(dac_end - dac_start) / dac_step)  # Dynamic wait time
            return self.get_iv_curve()
        finally:
            self.busy = False

    def get_iv_curve(self):
        iv_curve_values = [0,0]
        if self.is_opened:
            self.busy = True
            try:
                self.send_cmd('IVGE')
                data_str = self.stm_serial.readline().decode().strip()
                if data_str.startswith("IV"):
                    iv_curve_values = [int(x) for x in data_str.split(',')[1:]]
            except Exception as e:
                logger.error(f"Error getting IV curve: {e}")
            finally:
                self.busy = False
        return iv_curve_values

    def set_bias(self, value):
        self.send_cmd(f"BIAS {value}")

    def set_dacz(self, value):
        self.send_cmd(f"DACZ {value}")

    def set_dacx(self, value):
        self.send_cmd(f"DACX {value}")

    def set_dacy(self, value):
        self.send_cmd(f"DACY {value}")

    def turn_on_const_current(self, target_adc):
        self.send_cmd(f"CCON {target_adc}")

    def turn_off_const_current(self):
        self.send_cmd(f"CCOF")

    def set_pid(self, Kp, Ki, Kd):
        self.send_cmd(f"PIDS {Kp} {Ki} {Kd}")

    def start_scan(self, x_start, x_end, x_resolution, y_start, y_end, y_resolution, sample_number):
        """Enhanced scanning with two-stage approach"""
        if self.busy:
            return

        self.busy = True
        try:
            # First do a coarse scan to find interesting areas
            coarse_resolution = max(x_resolution // 10, y_resolution // 10, 10)
            self._perform_scan(x_start, x_end, coarse_resolution,
                               y_start, y_end, coarse_resolution,
                               sample_number, "Coarse scan")

            # Analyze coarse scan to find areas of interest
            interesting_areas = self._find_interesting_areas()

            # Then do fine scans on interesting areas
            for area in interesting_areas:
                ax_start, ax_end, ay_start, ay_end = area
                self._perform_scan(ax_start, ax_end, x_resolution,
                                   ay_start, ay_end, y_resolution,
                                   sample_number, "Fine scan")

        finally:
            self.busy = False

    def _perform_scan(self, x_start, x_end, x_resolution,
                      y_start, y_end, y_resolution, sample_number, scan_type):
        """Perform a single scan with given parameters"""
        logger.info(f"Starting {scan_type}: X={x_start}-{x_end} ({x_resolution}), Y={y_start}-{y_end} ({y_resolution})")

        self.scan_config = [x_start, x_end, x_resolution, y_start, y_end, y_resolution]
        self.send_cmd(f"SCST {x_start} {x_end} {x_resolution} {y_start} {y_end} {y_resolution} {sample_number}")

        # Initialize scan arrays
        self.scan_adc = np.zeros([x_resolution, y_resolution], dtype=np.float32)
        self.scan_dacz = np.zeros([x_resolution, y_resolution], dtype=np.float32)

        current_line = ''
        scan_complete = False

        while not scan_complete:
            if not self.is_opened:
                break

            # Process available data
            while self.stm_serial.in_waiting > 0:
                read_str = self.stm_serial.read(self.stm_serial.in_waiting).decode()

                # Handle line breaks
                if '\n' in read_str:
                    lines = read_str.split('\n')
                    for line in lines:
                        if line.endswith('\r'):
                            scan_complete = self._process_scan_line(current_line + line)
                            current_line = ''
                        else:
                            current_line += line
                else:
                    current_line += read_str

            # Process any complete line we have
            if current_line.endswith('\r'):
                scan_complete = self._process_scan_line(current_line)
                current_line = ''

            time.sleep(0.01)  # Small delay to prevent CPU overload

        logger.info(f"{scan_type} completed")

    def _process_scan_line(self, line):
        """Process a single line of scan data"""
        data = line.split(',')
        if not data:
            return False

        data_type = data[0]

        if data_type == "A":  # ADC data
            if len(data) >= 3:
                x_i = int(data[1])
                self.scan_adc[x_i, :] = [int(x) for x in data[2:]]
        elif data_type == "Z":  # DACZ data
            if len(data) >= 3:
                x_i = int(data[1])
                self.scan_dacz[x_i, :] = [int(x) for x in data[2:]]
        elif data_type == "D":  # Done
            return True

        return False

    def _find_interesting_areas(self):
        """Analyze scan data to find areas of interest for fine scanning"""
        if self.scan_adc is None:
            return []

        # Simple threshold-based approach - can be enhanced
        threshold = np.percentile(self.scan_adc, 90)  # Top 10% values
        interesting_points = np.argwhere(self.scan_adc > threshold)

        if len(interesting_points) == 0:
            return []

        # Cluster nearby points
        from sklearn.cluster import DBSCAN
        clustering = DBSCAN(eps=5, min_samples=3).fit(interesting_points)

        areas = []
        for label in set(clustering.labels_):
            if label == -1:  # Noise
                continue

            cluster_points = interesting_points[clustering.labels_ == label]
            min_x, min_y = cluster_points.min(axis=0)
            max_x, max_y = cluster_points.max(axis=0)

            # Convert pixel coordinates to DAC values
            x_start = self.scan_config[0] + (min_x / self.scan_config[2]) * (self.scan_config[1] - self.scan_config[0])
            x_end = self.scan_config[0] + (max_x / self.scan_config[2]) * (self.scan_config[1] - self.scan_config[0])
            y_start = self.scan_config[3] + (min_y / self.scan_config[5]) * (self.scan_config[4] - self.scan_config[3])
            y_end = self.scan_config[3] + (max_y / self.scan_config[5]) * (self.scan_config[4] - self.scan_config[3])

            # Add some padding
            x_pad = (x_end - x_start) * 0.2
            y_pad = (y_end - y_start) * 0.2
            areas.append((
                max(0, x_start - x_pad),
                min(65535, x_end + x_pad),
                max(0, y_start - y_pad),
                min(65535, y_end + y_pad)
            ))

        return areas

    def auto_approach(self, target_adc,max_steps=1000,corse_step = 10, fine_step=1):

        current_status = self.get_status()

        safe_margin = 0.2 * target_adc
        coarse_threshold = 0.5 * target_adc
        for step in range(max_steps):
            current_adc = current_status.adc
            error = target_adc - current_adc
            if abs(error) > coarse_threshold:
                step_size = corse_step
            else:
                step_size = fine_step
            direction = 1 if error >0 else -1
            self.move_motor(direction * step_size)
            time.sleep(0.3)
            current_status = self.get_status()

            if abs(error) < 0.01 * target_adc:
                logger.info(f"Auto approach completed. Current: {current_status.adc:.3e}A (Target: {target_adc:.3e})")
                return  True
        return False