from multiprocessing import Process, Queue
from queue import Empty
from styles import StyledCTkLabel
from image_tiling import *
import inspect
from constants import IMAGE_TILE_SIZE, IMAGE_TILE_OVERLAP, FUNC_EXCEPTIONS

progress_bar_mode_indeterminate = True

def update_progress(self, progress):
    global progress_bar_mode_indeterminate
    self.change_progress_state("determinate")
    progress_bar_mode_indeterminate = False
    if self.progress_label.winfo_exists() and self.progress_bar.winfo_exists():
        self.progress_label.configure(text=f"Progress: {int(progress)}%")
        self.progress_bar.set(int(progress) / 100)

def check_progress(self):
    global progress_bar_mode_indeterminate
    try:
        progress = self.progress_queue.get_nowait()
        self.update_progress(progress)
    except Empty:
        if progress_bar_mode_indeterminate:
            self.change_progress_state("indeterminate")

    self.root.after(1, self.check_progress)

def cancel_progress(self):
    if self.processing_thread.is_alive():
        self.processing_thread.terminate()
        self.processing_thread.join()
    
    self.popup.destroy()
    self.enable_app_tools()
    self.canvas.config(state='normal')

def image_processing_wrapper(func, input_img, queue, progress_queue, func_args):
    try:
        if func.__name__ not in FUNC_EXCEPTIONS:
            tiles, positions, valid_sizes, original_size = tile_image_with_overlap(input_img, IMAGE_TILE_SIZE, IMAGE_TILE_OVERLAP)
            
            processed_tiles = []
            for index, tile in enumerate(tiles):
                result = func(tile, progress_queue, *func_args)
                processed_tiles.append(result)
                progress_queue.put(((index + 1) / len(tiles)) * 100)
                
            # Stitch all upscaled tiles
            processed_image = stitch_tiles_with_blending(tiles, 
                                                         positions, 
                                                         valid_sizes, 
                                                         original_size,
                                                         IMAGE_TILE_SIZE,
                                                         IMAGE_TILE_OVERLAP)
            
            queue.put(processed_image) 
        else:
            result = func(input_img, progress_queue, *func_args)
            queue.put(result)
            
    except Exception as e:
        queue.put(e)

def start_processing(self, function, values):
    self.disable_app_tools()
    self.canvas.config(state='disabled')
    self.show_progress_popup()

    self.popup.update_idletasks()
    self.popup.update()

    self.root.after(10, lambda: self.run_processing_pipeline(function, values))

def run_processing_pipeline(self, function, values):
    try:
        # Preprocess image
        pre_processed_image = self.apply_settings(self.current_image_id, 'actual_frame')
        values = self.generate_function_arguments(values)
        
        # adding information label update popup text
        func_args = list(inspect.signature(function).parameters.values())
        self.information_label = StyledCTkLabel(self.progress_frame, text="")
        self.information_label.grid(row=1, column=0, padx=10, pady=(0, 5))
        args_to_text = ""
        for index, param in enumerate(func_args[2:]):
            args_to_text += f"\n{param.name}: {values[index]}"
            
        self.change_progress_status_text(f"Running: {function.__name__}{args_to_text}")
        self.progress_label.configure(text="Processing...")
        
        self.popup.update_idletasks()
        self.popup.update()
        
        # Setup queue and processing
        self.results_queue = Queue()
        self.progress_queue = Queue()
        
        self.processing_thread = Process(
            target=image_processing_wrapper,
            args=(function, pre_processed_image, self.results_queue, self.progress_queue, values),
            daemon=True
        )
        self.processing_thread.start()
        
        # Setup cancel button
        self.cancel_progress_button.configure(command=self.cancel_progress)
        self.root.after(1, self.check_progress)
        
        # Force popup to render immediately
        self.popup.update_idletasks()
        self.popup.update()
        
        # Start polling for results
        self.root.after(100, self.check_process_result)

    except Exception as e:
        self.popup.destroy()
        self.show_error_popup(str(e))
        self.enable_app_tools()
        self.canvas.config(state='normal')

def check_process_result(self):
    try:
        result = self.results_queue.get_nowait()

        # Handle exceptions that may have been passed back
        if isinstance(result, Exception):
            raise result

        # Success
        self.popup.destroy()
        self.enable_app_tools()
        self.canvas.config(state='normal')
        
        self.build_history(result)


    except Empty:
        # Force popup to render immediately
        self.popup.update_idletasks()
        self.popup.update()
        
        self.root.after(100, self.check_process_result)

    except Exception as e:
        self.popup.destroy()
        self.show_error_popup(str(e))
        self.enable_app_tools()
        self.canvas.config(state='normal')