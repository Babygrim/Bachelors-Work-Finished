from constants import *
import tkinter as tk
from PIL import ImageTk

def generate_function_arguments(self, selectors):
    args = []
    for controllers in DEFAULT_VALUE_SELECTION_METHODS:
        for controller in selectors[controllers]:
            if controllers == 'switch':
                effect_value = controller[0].get()
            elif controllers == 'slider':
                effect_value = round(float(controller[0].get()) / 100, 2)
            else:
                effect_value = controller[0].get() 
                
            args.append(effect_value)
    
    return args

def reset_module_tools(self, module: str):
    '''Resetting all the regulators to their default values -> lookup constants.py file

       objects -> dict of dicts

       Object representation is as follows: name: (executable, value_regulators, text_variables)
       
       name -> effect name (literal made by me)
       
       executable -> func or class (optional)
       
       value_regulator -> dict with slider/switch/checkbox objects related to a 'name' (function)
       
       text_variables -> dict with text values related to slider/switch/chebox objects related to a 'name' (function)
    ''' 
    app = self.app_methods.get(module, None)

    if app:
        for method in app.keys():
            for name, (_, value_regulators, text_variables) in app[method].items():
                for controllers in DEFAULT_VALUE_SELECTION_METHODS:
                    for i, controller in enumerate(value_regulators[controllers]):
                        if controllers == 'switch':
                            controller[0].set(DEFAULT_SWITCH_METHOD_OFF_VALUE)
                            text_variables[controllers][i][1].configure(text=f"{text_variables[controllers][i][0]} (OFF)")
                        elif controllers == 'slider':
                            controller[0].set(DEFAULT_SLIDER_VALUES[name])
                            text_variables[controllers][i][1].configure(text=f"{text_variables[controllers][i][0]} ({DEFAULT_SLIDER_VALUES[name]/100:.2f})")
                            
def load_module_settings(self, frame_id, module: str = ""):
    '''Set regulator values according to settings passed
       
       Method objects are built as follows: name: (executable, value_regulators, text_variables)
       
       name -> effect name (literal made by me) 
       
       executable -> func or class
       
       value_regulator -> dict with slider/switch/checkbox objects related to a 'name' (function)
       
       text_variables -> dict with text values related to slider/switch/chebox objects related to a 'name' (function) 
    '''
    try:
        settings = self.image_history[frame_id].get('settings', None).get(module, None)
        app = self.app_methods.get(module, None)
    except KeyError:
        settings = None
    
    if settings:
        for method in settings.keys():
            for bound_name, (_, value_regulators, text_variables) in settings[method].items():
                for controllers in DEFAULT_VALUE_SELECTION_METHODS:
                    for i, controller in enumerate(value_regulators[controllers]):
                        
                        current_controller = app[method][bound_name][1][controllers][i][0]
                        current_controller.set(controller[1])
                        self.image_history[frame_id]['settings'][module][method][bound_name][1][controllers][i] = (current_controller, controller[1])

                        if text_variables:
                            current_text_variables = app[method][bound_name][2][controllers]
                            
                            if controllers == 'switch':
                                    current_text_variables[i][1].configure(text=f"{text_variables[controllers][i][0]} {"(ON)" if controller[1] else "(OFF)"}")
                                    self.image_history[frame_id]['settings'][module][method][bound_name][2][controllers][i]  = (text_variables[controllers][i][0], current_text_variables[i][1])
                            elif controllers == 'slider':
                                    current_text_variables[i][1].configure(text=f"{text_variables[controllers][i][0]} ({controller[1] / 100:.2f})")
                                    self.image_history[frame_id]['settings'][module][method][bound_name][2][controllers][i]  = (text_variables[controllers][i][0], current_text_variables[i][1])
                        

def change_items_state(self, items: list, state: str):
    for item in items:
        item.configure(state=state)
    
def display_on_canvas(self, image, anchor_x = 0, anchor_y = 0, initial=True):
    self.tkinter_image = ImageTk.PhotoImage(image)
    
    #prepare canvas
    new_width, new_height = image.size
    self.canvas.config(width=new_width, height=new_height)
    self.canvas.update()

    anchor_x = anchor_x if anchor_x else self.canvas.winfo_width()/2
    anchor_y = anchor_y if anchor_y else self.canvas.winfo_height()/2
    
    
    if initial:
        self.image_container = self.canvas.create_image(anchor_x, anchor_y, anchor=tk.CENTER, image=self.tkinter_image)
        
        #Image crop listeners
        self.canvas.tag_bind(self.image_container, "<Control-ButtonPress-1>", self.start_selection)
        self.canvas.tag_bind(self.image_container, "<Control-B1-Motion>", self.update_selection)
        self.canvas.tag_bind(self.image_container, "<Control-ButtonRelease-1>", self.finalize_selection)
        self.root.bind("<KeyRelease-Control_L>", self.interrupt_crop)
        self.root.bind("<KeyRelease-Control_R>", self.interrupt_crop)
        
        #Image scale listeners
        bind_all_children(self.canvas_wrapper, "<Shift-MouseWheel>", self.zoom) #Windows/mac
        bind_all_children(self.canvas_wrapper, "<Shift-Button-4>", self.zoom) #linux
        bind_all_children(self.canvas_wrapper, "<Shift-Button-5>", self.zoom) #linux
        bind_all_children(self.canvas_wrapper, "<Shift-ButtonPress-1>", self.start_drag)
        bind_all_children(self.canvas_wrapper, "<Shift-B1-Motion>", self.do_drag)
        bind_all_children(self.canvas_wrapper, "<Configure>", lambda e: self.keep_image_in_bounds())
    else:
        self.canvas.itemconfig(self.image_container, image=self.tkinter_image)
        self.canvas.coords(self.image_container, anchor_x, anchor_y)
      
    coords = self.canvas.coords(self.image_container)
    self.image_history[self.current_image_id]["anchor_data"] = {'x': round(coords[0], 3), 'y': round(coords[1], 3)}
        
def load_unchanged_image(self):
    cur_frame_obj = self.image_history[self.current_image_id]

    image, scale = self.resize_image(cur_frame_obj['actual_frame'],
                                     new_height=cur_frame_obj['actual_frame'].height * cur_frame_obj['scale'],
                                     new_width=cur_frame_obj['actual_frame'].width * cur_frame_obj['scale'])
       
    cur_frame_obj['placeholder_frame'] = image
    for modules in self.app_modules.keys():
        if modules != self.current_app_module:
            cur_frame_obj['placeholder_frame'] = self.apply_settings(self.current_image_id, 'placeholder_frame', module_name=modules)
        
    self.placeholder_image = self.modified_image = cur_frame_obj['placeholder_frame']
    self.display_on_canvas(self.placeholder_image)

    # some shenanigans :)
    self.image_history[self.current_image_id]["used_function"] = None
    
    self.update_scale(scale * 100)
    self.reset_module_tools(self.current_app_module)
        
def disable_app_tools(self):
    self.change_items_state(self.module_toolframe.winfo_children(), 'disabled')
    self.change_items_state(self.top_toolbar.winfo_children(), 'disabled')
    self.change_items_state(self.photo_frame_extra.winfo_children(), 'disabled')
    self.change_items_state(self.image_toolbar.winfo_children(), 'disabled')
    
def enable_app_tools(self):
    self.change_items_state(self.module_toolframe.winfo_children(), 'normal')
    self.change_items_state(self.top_toolbar.winfo_children(), 'normal')
    self.change_items_state(self.photo_frame_extra.winfo_children(), 'normal')
    self.change_items_state(self.image_toolbar.winfo_children(), 'normal')
    
def update_scale(self, value):
    self.scale_slider.configure(state='disabled')
    self.scale_slider.set(value)
    self.scale_label.configure(text=f"Scale ({value / 100:.2f})")
    
def bind_all_children(widget, sequence, func):
    widget.bind(sequence, func)
    for child in widget.winfo_children():
        bind_all_children(child, sequence, func)