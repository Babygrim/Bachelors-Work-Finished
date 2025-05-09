import tkinter as tk
from PIL import ImageTk
import string
import random
from constants import *

def generate_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits + string.ascii_lowercase, k=12))

# IMAGE HISTORY LOGIC
def build_history(self, photo_image, initial=True, reference_name=None, extension_name=None):
    new_image_id = generate_id()
    
    photo_holder = tk.Label(self.photo_frame_extra, height=150, width=self.photo_frame_extra.winfo_width())
    #ttk.Label(self.photo_frame_extra, text=f"Item {i+1}", padding=5).pack(anchor="w", padx=10, pady=2)
    
    photo_holder.pack(fill='x', padx=10, pady=2)
    photo_holder.bind("<Button-1>", lambda event: self.load_history(event=event, new_history_id=new_image_id, initial=False))
    photo_holder.update()
    # self.update_scroll_region()
    
    history_resized, _ = self.resize_image(photo_image, photo_holder, rescale=0.9)
    main_frame_resized, scale = self.resize_image(photo_image, self.main_frame)
    
    # try to load parent settings
    if not initial:
        pass
    
    # create new reference image history object
    self.image_history[new_image_id] = {"main_frame": main_frame_resized, 
                                        "placeholder_frame": main_frame_resized,
                                        "initial_scale": scale,
                                        "scale": scale,
                                        "actual_frame": photo_image,
                                        "actual_frame_size": str(photo_image.size[0]) + "x" + str(photo_image.size[1]),
                                        "visible_frame_size": str(main_frame_resized.size[0]) + "x" + str(main_frame_resized.size[1]),
                                        "reference_name": reference_name if reference_name else self.image_history[self.current_image_id]['reference_name'],
                                        "extension_name": extension_name if extension_name else self.image_history[self.current_image_id]['extension_name'],
                                        "parent_frame_id": self.current_image_id,
                                        "history_frame": ImageTk.PhotoImage(history_resized),
                                        "history_frame_object": photo_holder, 
                                        "used_function": None,
                                        "settings": dict(),
                                        "drag_data": {"x": 0, "y": 0},
                                        "anchor_data": {"x": 0, "y": 0},
                                    }
    
    self.load_history(event=True, new_history_id = new_image_id, initial=initial)

def save_history(self, module):
    try:
        current_photo_object = self.image_history[self.current_image_id]
        
        # get module methods
        methods = self.app_methods.get(module, None)
        module_settings = {module: dict()}
        
        if methods:
            for method_type in methods.keys():
                method_vars = dict()
                for name, (effect_class, selectors, text_variables) in methods[method_type].items():
                    controllers = dict()
                    for method in DEFAULT_VALUE_SELECTION_METHODS:
                        updated = []
                        for controller in selectors[method]:
                            updated.append((controller[0], controller[0].get()))
                            
                        controllers.update({method: updated})
                    
                    method_vars.update({name: (effect_class, controllers, text_variables)})
                
                module_settings[module].update({method_type: method_vars})
            
            current_photo_object["settings"].update(module_settings)
            current_photo_object["main_frame"] = self.placeholder_image
            coords = self.canvas.coords(self.image_container)
            current_photo_object["anchor_data"] = {'x': round(coords[0], 3), 'y': round(coords[1], 3)}
    except KeyError:
        pass
        
def load_history(self, event, new_history_id, initial):
    '''If initial is set to True - load new image and load default settings,
       else - load new image and load new settings'''  
    if self.current_image_id != new_history_id:
        new_history_object = self.image_history[new_history_id]
        get_Label_object = new_history_object["history_frame_object"]

        # save old - potentially, modified image and it's settings
        self.save_history(self.current_app_module)
        
        if initial:
            #reset settings if image is not first
            if self.current_image_id != None:
                self.reset_module_tools(self.current_app_module)
            
            #load new history Image
            get_Label_object.config(image=new_history_object.get("history_frame"))
            get_Label_object.config(state='active')
            self.photo_frame_extra.update()
        else:
            #load new settings
            self.load_module_settings(new_history_id, self.current_app_module)
        
        # set new reference history object     
        self.current_image_id = new_history_id
        
        # some shenanigans :)
        self.image_history[self.current_image_id]["used_function"] = None
        
        # main display image
        self.modified_image = new_history_object.get("placeholder_frame")
        self.placeholder_image = new_history_object.get("main_frame")
        self.update_scale(new_history_object.get('scale') * 100)
        
        self.display_on_canvas(self.placeholder_image, 
                               new_history_object['anchor_data']['x'], 
                               new_history_object['anchor_data']['y'], 
                               initial)
        
        #Image info loaded
        if DEBUG:
            self.build_overlay()
            self.update_overlay_text()
    
    if event == True:
        self.change_items_state(self.photo_frame_extra.winfo_children(), 'disable')
        self.change_items_state([get_Label_object], 'active')
    
    elif event:
        self.change_items_state(self.photo_frame_extra.winfo_children(), 'disable')
        self.change_items_state([event.widget], 'active')