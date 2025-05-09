from math import ceil
from PIL import ImageTk, Image
from _tkinter import TclError
from constants import DEFAULT_VALUE_SELECTION_METHODS

#effects management and feed to canvas
def display_image(callback):
        current_func = None
        
        def wrapper(*args, **kwargs):
            nonlocal current_func
            self = args[0]
             
            try:
                current_photo_object = self.image_history[self.current_image_id]
                current_func = current_photo_object['used_function']

                if current_func != kwargs['function']:
                    current_func = current_photo_object['used_function'] = kwargs['function']                  

                    # handling applied methods
                    try:
                        if kwargs['function'].__module__ == 'img_scaling':
                            current_photo_object['main_frame'] = self.apply_settings(self.current_image_id, reference='actual_frame', function_check=current_func)
                        else:
                            current_photo_object['main_frame'], _ = self.resize_image(current_photo_object['actual_frame'], 
                                                                                new_width=current_photo_object['actual_frame'].width * current_photo_object['scale'],
                                                                                new_height=current_photo_object['actual_frame'].height * current_photo_object['scale'])
                            
                        self.modified_image = self.apply_settings(self.current_image_id, reference='main_frame', function_check=current_func)
                    except:
                        print('smth is happening')
                        print('we fucked')
            except KeyError:
                pass

            # Call original method
            callback(*args, **kwargs)
            
            # Update the tkinter image display
            try:
                self.tkinter_image = ImageTk.PhotoImage(self.placeholder_image)
                self.canvas.itemconfig(self.image_container, image=self.tkinter_image)
                current_photo_object['placeholder_frame'] = self.placeholder_image
            except TclError:
                pass
        
        return wrapper

#resize TO_FIT - will probably implement TO_COVER as well
def resize_image(self, photo_image, frame_ref=None, rescale = 0.9, new_height=None, new_width=None):
    #self.photo_frame.unbind("<Configure>")
    
    if frame_ref:
        frame_h, frame_w = frame_ref.winfo_height(), frame_ref.winfo_width()
        img_w, img_h = photo_image.size
        scale_w = min(frame_w / img_w, 1.0)
        scale_h = min(frame_h / img_h, 1.0)
        true_scale = min(scale_h, scale_w, 1.0) * rescale 
        resized = photo_image.resize((ceil(img_w*true_scale), ceil(img_h*true_scale)), Image.Resampling.BICUBIC)        
    
    if new_height and new_width:
        true_scale = 1.00
        resized = photo_image.resize((ceil(new_width), ceil(new_height)), Image.Resampling.BICUBIC)
    
    return resized, true_scale
    #self.photo_frame.bind("<Configure>", self.resize_image)

#effects application AND text labels altering
@display_image
def modify_image(self, values: dict, function, text_value, type):
    if type == 'slider': # sliders - return image with effect applied to an image, strenght of effect is determined by current slider value
        effect_value = round(float(values[type][0][0].get()) / 100, 2)
        
        if function.__module__ == "PIL.ImageEnhance":
            effect_enhancement = function(self.modified_image)
            self.placeholder_image = effect_enhancement.enhance(effect_value)
        elif function.__module__ == "PIL.ImageFilter":
            self.placeholder_image = self.modified_image.filter(function(effect_value))
        else:
            args = self.generate_function_arguments(values)
            self.placeholder_image = function(self.modified_image, *args)     
        
        effect_value = f"{float(values['slider'][0][0].get()) / 100:.2f}"
    elif type == 'switch': # switches - return image with settings that can be turned on/off
        if values[type][0][0].get():
            args = self.generate_function_arguments(values)
            self.placeholder_image = function(self.modified_image, *args)
            effect_value = "ON"
        else:
            self.placeholder_image = self.modified_image
            effect_value = "OFF"
        
    elif type == 'processing': # processing - no return, process handler runs in separate thread
        self.start_processing(function, values)
            
    elif type == 'helper': # helpers - utilize the functionality that changes label text
        if values['switch']:
            effect_value = "ON" if values['switch'][0][0].get() else "OFF"
        elif values['slider']:
            effect_value = f"{float(values['slider'][0][0].get()) / 100:.2f}"
        else:
            effect_value = values['checkbox'][0][0].get()
            
        if function:
            function()
            
    else: # rest of the functions - no use for now, except zoom functionality
        function(self.modified_image)
        
    if text_value:
        text_value[1].configure(text=f"{text_value[0]} ({effect_value})")

#apply saved image settings to image
def apply_settings(self, frame_id: str, reference: str, function_check = None, module_name: str = ""):
    image_to_apply = self.image_history[frame_id][reference].copy()
    
    if module_name != "":
        settings = [self.app_methods.get(module_name, None)]
    else:
        settings = [self.app_methods.get(module, None) for module in self.app_modules.keys()]
    
    
    for setting in settings:
        if setting:
            slider_methods = setting.get('slider_methods', dict())
            switch_methods = setting.get('switch_methods', dict())

            for _, (effect_class, controllers, _) in slider_methods.items():
                if function_check != effect_class:
                
                    if effect_class.__module__ == "PIL.ImageEnhance":
                        effect_enhancer = effect_class(image_to_apply)
                        image_to_apply = effect_enhancer.enhance(float(controllers['slider'][0][0].get()) / 100)
                    elif effect_class.__module__ == "PIL.ImageFilter":
                        effected_image = image_to_apply.filter(effect_class(float(controllers['slider'][0][0].get()) / 100))
                        image_to_apply = effected_image
                    else:
                        args = self.generate_function_arguments(controllers)
                        image_to_apply = effect_class(image_to_apply, *args)

                
            # handling switch_methods
            for _, (effect_func, controllers, _) in switch_methods.items():
                if function_check != effect_func:
                            
                    if controllers['switch'][0][0].get():
                        args = self.generate_function_arguments(controllers)
                        image_to_apply = effect_func(image_to_apply, *args)
        
    return image_to_apply