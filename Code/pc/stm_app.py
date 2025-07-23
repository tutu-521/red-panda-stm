from datetime import datetime
import tkinter as tk
from tkinter import ttk
import numpy as np
import stm_control
import time
import csv
import threading
from queue import Queue
from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg, NavigationToolbar2Tk)
from matplotlib.figure import Figure
from matplotlib import rcParams

rcParams.update({'figure.autolayout': True})

def save_data_to_file(filename_prefix, data_to_store: list):
    current_time_stamp = datetime.now()
    ts = int(datetime.timestamp(current_time_stamp) * 1000)
    with open(f"{filename_prefix}_{ts}.csv", 'w', newline='') as csvfile:
        datawriter = csv.writer(csvfile, delimiter=',',
                                quotechar='|', quoting=csv.QUOTE_MINIMAL)
        for data in data_to_store:
            datawriter.writerow(data)

class PlotFrame(ttk.Frame):
    def __init__(self, parent, with_toolbar=False, dpi=100.0, width=400, height=400, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.figure = Figure(figsize=(width / dpi, height / dpi), dpi=dpi)

        #Drawing area
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(side='top', fill='both', expand=True)

        if with_toolbar:
            self.toolbar = NavigationToolbar2Tk(self.canvas, self)
            self.toolbar.update()
            self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)

    def add_plot(self, label=None, xlabel=None, ylabel=None):
        self.plot = self.figure.add_subplot(111).plot([0, 1], [0, 0], '-', label=label)[0]
        ax = self.figure.get_axes()[0]
        ax.set_autoscalex_on(True)
        ax.set_autoscaley_on(True)
        ax.legend(loc='upper right')
        if xlabel: ax.set(xlabel=xlabel)
        if ylabel: ax.set(ylabel=ylabel)

    def add_image(self, image):
        self.image = self.figure.add_subplot(111).imshow(
            image, interpolation='none', norm=None, origin="lower")

    def update_plot(self, x_data, y_data):
        self.plot.set_xdata(x_data)
        self.plot.set_ydata(y_data)
        ax = self.figure.get_axes()[0]
        ax.relim()
        ax.autoscale_view()
        # We need to draw *and* flush
        self.canvas.draw()
        self.canvas.flush_events()

    def update_image(self, image_data, extend=None):
        self.image.set_data(image_data)
        self.image.autoscale()
        if extend:
            self.image.set_extent(extend)
        self.canvas.draw()
        self.canvas.flush_events()

    def save_figure(self, image_path):
        self.figure.savefig(image_path)
class _DAC_Control(ttk.Frame):
    def __init__(self, parent, text, default_value, cmd_func, convert_func, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.cmd_func = cmd_func
        self.convert_func = convert_func
        self.input_string_var = tk.StringVar(value=default_value)
        self.input_entry = ttk.Entry(self, textvariable=self.input_string_var, width=10)
        self.input_entry.grid(row=0, column=1, padx=5)

        self.display_var = tk.StringVar()
        self._update_display(default_value)

        self.display = ttk.Label(self, textvariable=self.display_var, width=10)
        self.display.grid(row=0, column=2, padx=5)
        self.button = ttk.Button(master=self, text=text, command=self.set_value)
        self.button.grid(row=0, column=0, padx=5)

    def _update_display(self, value):
        self.display_var.set(f"{self.convert_func(int(value)):.4f}")

    def set_value(self):
        target = self.input_string_var.get()
        self.cmd_func(int(target))
        self._update_display(target)


class _ButtonWithEntry(ttk.Frame):
    def __init__(self, parent, text, default_value_list, cmd_func, display_list=None, entry_width=10, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.input_string_var_list = []
        self.input_entry_list = []
        self.cmd_func = cmd_func
        row_button = 1 if display_list else 0

        for i in range(len(default_value_list)):
            if display_list and i < len(display_list) and display_list[i]:
                label = ttk.Label(self, text=display_list[i])
                label.grid(row=0, column=i + 1, padx=2)

            input_string_var = tk.StringVar(value=default_value_list[i])
            input_entry = ttk.Entry(self, textvariable=input_string_var, width=entry_width)
            input_entry.grid(row=row_button, column=i + 1, padx=2)
            self.input_string_var_list.append(input_string_var)
            self.input_entry_list.append(input_entry)

        button = ttk.Button(self, text=text, command=self._set_values)
        button.grid(row=row_button, column=0, padx=5)

    def _set_values(self):
        values = []
        for var in self.input_string_var_list:
            target = var.get()
            try:
                values.append(float(target) if '.' in target else int(target))
            except ValueError:
                values.append(target)
        self.cmd_func(*values)


class _ScanControl(ttk.Frame):
    def __init__(self, parent, cmd_func, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.var_list = []
        self.cmd_func = cmd_func

        # Labels
        ttk.Label(self, text="X Start").grid(row=0, column=1, padx=2)
        ttk.Label(self, text="X End").grid(row=0, column=2, padx=2)
        ttk.Label(self, text="X Res").grid(row=0, column=3, padx=2)
        ttk.Label(self, text="Y Start").grid(row=1, column=1, padx=2)
        ttk.Label(self, text="Y End").grid(row=1, column=2, padx=2)
        ttk.Label(self, text="Y Res").grid(row=1, column=3, padx=2)
        ttk.Label(self, text="Samples").grid(row=2, column=1, padx=2)

        # Entries for X and Y
        defaults = ["31768", "33768", "512"]
        for row in range(2):
            for col in range(3):
                var = tk.StringVar(value=defaults[col])
                entry = ttk.Entry(self, textvariable=var, width=8)
                entry.grid(row=row, column=col + 1, padx=2)
                self.var_list.append(var)

        # Sample number
        sample_var = tk.StringVar(value="10")
        ttk.Entry(self, textvariable=sample_var, width=8).grid(row=2, column=2, padx=2)
        self.var_list.append(sample_var)

        # Control Button
        ttk.Button(self, text="Scan", command=self._set_values).grid(row=2, column=0, padx=5)

    def _set_values(self):
        values = []
        for var in self.var_list:
            try:
                values.append(int(var.get()))
            except ValueError:
                values.append(var.get())
        self.cmd_func(*values)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.stm = stm_control.STM()
        self.baseline_size = 500
        self.title("Panda STM")
        self.queue = Queue()

        # Configure main window
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Control panel with scrollbar
        self.control_frame = ttk.Frame(self, width=self.baseline_size)
        self.control_frame.grid(row=0, column=0, sticky="nswe", padx=5, pady=5)

        canvas = tk.Canvas(self.control_frame)
        scrollbar = ttk.Scrollbar(self.control_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Image display area
        self.image_frame = ttk.Frame(self)
        self.image_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        # Configure image frame grid
        for i in range(2):
            self.image_frame.grid_rowconfigure(i, weight=1)
        for j in range(3):
            self.image_frame.grid_columnconfigure(j, weight=1)

        # Create UI components
        self._create_plots()
        self._create_control_panel(scrollable_frame)

        # Start update loops
        self._update_real_time()
        self._update_images()

        # Set initial window size to 90% of screen
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.geometry(f"{int(screen_width * 0.9)}x{int(screen_height * 0.8)}")
        self.minsize(int(screen_width * 0.6), int(screen_height * 0.6))

    def _create_plots(self):
        """Create all plot areas with reduced size"""
        plot_size = self.baseline_size
        # Real-time current plot
        self.real_time_current_plot_frame = PlotFrame(
            self.image_frame, dpi=100, with_toolbar=True, width=plot_size, height=plot_size // 2)
        self.real_time_current_plot_frame.add_plot(
            label="current", xlabel='time (s)', ylabel='adc)')
        self.real_time_current_plot_frame.grid(
            row=0, column=0, sticky="nsew", padx=5, pady=5)

        # Real-time steps plot
        self.real_time_steps_plot_frame = PlotFrame(
            self.image_frame, dpi=100, with_toolbar=True, width=plot_size, height=plot_size // 2)
        self.real_time_steps_plot_frame.add_plot(
            label="steps", xlabel='time (s)', ylabel='steps')
        self.real_time_steps_plot_frame.grid(
            row=0, column=1, sticky="nsew", padx=5, pady=5)

        # IV curve plot
        self.iv_curve_frame = PlotFrame(
            self.image_frame, dpi=100, with_toolbar=True, width=plot_size, height=plot_size // 2)
        self.iv_curve_frame.add_plot(
            label="IV Curve", xlabel="Bias", ylabel="ADC")
        self.iv_curve_frame.grid(
            row=1, column=1, sticky="nsew", padx=5, pady=5)

        # Scan image areas
        init_image = np.random.rand(10, 10)
        self.scan_dacz_frame = PlotFrame(
            self.image_frame, dpi=100, with_toolbar=True, width=plot_size, height=plot_size // 2)
        self.scan_dacz_frame.add_image(init_image)
        self.scan_dacz_frame.grid(
            row=0, column=2, sticky="nsew", padx=5, pady=5)

        self.scan_adc_frame = PlotFrame(
            self.image_frame, dpi=100, with_toolbar=True, width=plot_size, height=plot_size // 2)
        self.scan_adc_frame.add_image(init_image)
        self.scan_adc_frame.grid(
            row=1, column=2, sticky="nsew", padx=5, pady=5)

    def _create_control_panel(self, parent):
        """Create control panel widgets"""
        # Communication control
        comm_frame = ttk.LabelFrame(parent, text="Communication", padding=5)
        comm_frame.pack(fill='x', pady=5, padx=5)

        # Open port button
        open_frame = _ButtonWithEntry(comm_frame, "Open", ["COM7"], self.stm.open)
        open_frame.pack(fill='x', pady=2)

        btn_frame = ttk.Frame(comm_frame)
        btn_frame.pack(fill='x', pady=5)
        ttk.Button(btn_frame, text="STOP", command=self.stm.stop).pack(side='left', expand=True)
        ttk.Button(btn_frame, text="Reset", command=self.stm.reset).pack(side='left', expand=True)
        ttk.Button(btn_frame, text="Clear", command=self.stm.clear).pack(side='left', expand=True)

        # 2. DAC control
        dac_frame = ttk.LabelFrame(parent, text="DAC Control", padding=5)
        dac_frame.pack(fill='x', pady=5, padx=5)

        dac_controls = [
            ("Bias", "33314", self.stm.set_bias, stm_control.STM_Status.dac_to_bias_volts),
            ("DACZ", "32768", self.stm.set_dacz, stm_control.STM_Status.dac_to_dacz_volts),
            ("DACX", "32768", self.stm.set_dacx, stm_control.STM_Status.dac_to_dacx_volts),
            ("DACY", "32768", self.stm.set_dacy, stm_control.STM_Status.dac_to_dacy_volts)
        ]

        for text, default, cmd, convert in dac_controls:
            control = _DAC_Control(dac_frame, text, default, cmd, convert)
            control.pack(fill='x', pady=2)

            # Set all DACs button
        ttk.Button(dac_frame, text="Set All DACs", command=self._set_all_dac).pack(pady=5)

        # 3.Tip control
        approach_frame = ttk.LabelFrame(parent, text="Tip Control", padding=5)
        approach_frame.pack(fill='x', pady=5, padx=5)

        self.approach_control = _ButtonWithEntry(
            approach_frame, "Approach", ["500", "1"],
            self.stm.approach, ["Target DAC", "Step"]
        )
        self.approach_control.pack(fill='x', pady=2)

        ttk.Button(approach_frame, text="Auto Approach",
                   command=self._auto_approach).pack(fill='x', pady=5)
        # 4. IV curve measurement
        iv_frame = ttk.LabelFrame(parent, text="IV Curve", padding=5)
        iv_frame.pack(fill='x', pady=5, padx=5)

        iv_control = _ButtonWithEntry(
            iv_frame, "PlotIV",
            ["31768", "33768", "10"],
            self._plot_iv_curve)
        iv_control.pack(fill='x', pady=2)

        # Save IV curve
        save_iv = _ButtonWithEntry(
            iv_frame, "Save IV Data",
            ["./data/iv_curve_"],
            self._save_iv_curve,
            entry_width=20
        )
        save_iv.pack(fill='x', pady=2)

        # 5. Constant current mode
        cc_frame = ttk.LabelFrame(parent, text="Constant Current", padding=5)
        cc_frame.pack(fill='x', pady=5, padx=5)

        # PID settings
        pid_control = _ButtonWithEntry(
            cc_frame, "Set PID",
            ["0.0001", "0.0001", "0.0"],
            self.stm.set_pid,
            ["Kp", "Ki", "Kd"]
        )
        pid_control.pack(fill='x', pady=2)

        # CC mode buttons
        cc_btn_frame = ttk.Frame(cc_frame)
        cc_btn_frame.pack(fill='x', pady=2)
        ttk.Button(cc_btn_frame, text="CC On",
                   command=lambda: self.stm.turn_on_const_current(1000)).pack(side='left', padx=2)
        ttk.Button(cc_btn_frame, text="CC Off",
                   command=self.stm.turn_off_const_current).pack(side='left', padx=2)

        # 6. Scan control
        scan_frame = ttk.LabelFrame(parent, text="Scan Control", padding=5)
        scan_frame.pack(fill='x', pady=5, padx=5)

        scan_control = _ScanControl(scan_frame, self._scan_and_plot)
        scan_control.pack(fill='x', pady=2)

        # Save scan image
        save_scan = _ButtonWithEntry(
            scan_frame, "Save Scan",
            ["./data/scan_"],
            self._save_scan_image,
            entry_width=20
        )
        save_scan.pack(fill='x', pady=2)

        # 7. Direct command
        cmd_frame = ttk.LabelFrame(parent, text="Direct Command", padding=5)
        cmd_frame.pack(fill='x', pady=5, padx=5)

        self.cmd_entry = ttk.Entry(cmd_frame)
        self.cmd_entry.pack(fill='x', pady=2)
        ttk.Button(cmd_frame, text="Send", command=self._send_cmd).pack(pady=2)

        # Status display
        self.status_label = ttk.Label(
            parent,
            text="Status: Waiting for connection...",
            relief="ridge",
            padding=5,
            wraplength=self.baseline_size - 20
        )
        self.status_label.pack(fill='x', pady=10, padx=5)

    def _set_all_dac(self):
        # Find all DAC controls in the children widgets
        for child in self.control_frames.winfo_children():
            if isinstance(child, _DAC_Control):
                child.set_value()
                time.sleep(0.01)
    def _plot_iv_curve(self, *args):
        """Plot IV curve"""
        iv_curve_values = self.stm.measure_iv_curve(*args)
        x_value = iv_curve_values[::2]
        y_value = iv_curve_values[1::2]
        current = [stm_control.STM_Status.adc_to_amp(adc) for adc in y_value]
        bias = [stm_control.STM_Status.dac_to_bias_volts(dac) for dac in x_value]
        self.iv_curve_frame.update_plot(bias, current)

    def _save_iv_curve(self, filename_prefix):
        """Save IV curve data"""
        iv_curve_values = self.stm.get_iv_curve()
        x_value = iv_curve_values[::2]
        y_value = iv_curve_values[1::2]
        save_data_to_file(filename_prefix, zip(x_value, y_value))

    def _scan_and_plot(self, *args):
        """Perform scan and plot results"""
        scan_thread = threading.Thread(target=self.stm.start_scan, args=args)
        scan_thread.start()

    def _save_scan_image(self, image_path_prefix):
        """Save scan image"""
        current_time_stamp = datetime.now()
        ts = int(datetime.timestamp(current_time_stamp) * 1000)
        np.savetxt(f"{image_path_prefix}_adc_{ts}.txt", self.stm.scan_adc)
        np.savetxt(f"{image_path_prefix}_dacz_{ts}.txt", self.stm.scan_dacz)
        self.scan_adc_frame.save_figure(f"{image_path_prefix}_adc_{ts}.png")
        self.scan_dacz_frame.save_figure(f"{image_path_prefix}_dacz_{ts}.png")

    def _send_cmd(self):
        """Send direct command"""
        cmd = self.cmd_entry.get()
        self.stm.send_cmd(cmd)
    def _threaded_action(self, func, *args):
        """Run a function in a thread to prevent UI freezing"""
        thread = threading.Thread(target=func, args=args)
        thread.daemon = True
        thread.start()

    def _auto_approach(self):
        """Start auto approach with current target"""
        target_dac = int(self.approach_control.input_string_var_list[0].get())
        self._threaded_action(self.stm.auto_approach, target_dac)

    def _start_scan(self):
        """Start scanning with current parameters"""
        args = (
            self.x_start_var.get(),
            self.x_end_var.get(),
            self.resolution_var.get(),
            self.y_start_var.get(),
            self.y_end_var.get(),
            self.resolution_var.get(),
            self.samples_var.get()
        )
        self._threaded_action(self.stm.start_scan, *args)

    def _measure_iv(self):
        """Measure IV curve with current parameters"""
        args = (
            self.iv_start_var.get(),
            self.iv_end_var.get(),
            self.iv_steps_var.get()
        )
        self._threaded_action(self.stm.measure_iv_curve, *args)

    def _update_real_time(self):
        """Update real-time plots"""
        status = self.stm.get_status()
        self.status_label.config(text=status.to_string())

        if self.stm.history:
            plot_x = [hist.time_millis for hist in self.stm.history]
            max_time = max(plot_x)
            plot_x = [(x - max_time) / self.baseline_size * 2.0 for x in plot_x]

            plot_adc = [stm_control.STM_Status.adc_to_amp(hist.adc) for hist in self.stm.history]
            plot_steps = [hist.steps for hist in self.stm.history]

            self.real_time_current_plot_frame.update_plot(plot_x, plot_adc)
            self.real_time_steps_plot_frame.update_plot(plot_x, plot_steps)

        self.after(100, self._update_real_time)

    def _update_images(self):
        if hasattr(self.stm, 'scan_config') and self.stm.scan_config:
            x_start, x_end, x_resolution, y_start, y_end, y_resolution = self.stm.scan_config
            if hasattr(self.stm, 'scan_adc'):
                self.scan_adc_frame.update_image(self.stm.scan_adc, extend=[
                    y_start, y_end, x_start, x_end])
            if hasattr(self.stm, 'scan_dacz'):
                self.scan_dacz_frame.update_image(
                    self.stm.scan_dacz, [y_start, y_end, x_start, x_end])

        self.after(500, self._update_images)


if __name__ == "__main__":
    app = App()
    app.mainloop()