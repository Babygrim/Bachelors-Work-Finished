from tkinter import filedialog, messagebox
import os
from PIL import Image
from app_popups import show_warning_popup

# choose and place image on canvas
def get_image(self):
    filename = filedialog.askopenfilename(initialdir=os.getcwd(), filetypes=[("Picture Files", ".jpeg .png .webp .svg .jpg")])
    if filename:
        extracted_image = Image.open(filename).convert("RGBA")
        reference_name, file_extension = os.path.splitext(filename)
        
        image_reference_name = reference_name.split('/')[-1]
        image_extension_name = file_extension.split('.')[-1]
        
        # hide add button
        self.add_pic_button.place_forget()
        
        # activate base functions
        self.enable_app_tools()
        
        # initialize history tree
        self.build_history(extracted_image, reference_name=image_reference_name, extension_name=image_extension_name)
        #self.current_image_id = self.image_history.keys()[0]

# remove image from canvas
@show_warning_popup(message="Image will be destroyed. All modifications will be lost.\nDo you wish to proceed?")
def remove_image(self):
    self.image_history[self.current_image_id]['history_frame_object'].destroy()
    del self.image_history[self.current_image_id]
    
    if len(self.image_history.keys()) == 0:
        self.canvas.destroy()
        self.reset_module_tools(self.current_app_module)
        self.current_image_id = None
        self.build_canvas()
        self.disable_app_tools()
    else:
        default_return = list(self.image_history.keys())[-1]
        self.load_history(event=True, initial=False, new_history_id=default_return)

# save modified image to chosen directory
def save_image(self):
    file_path = filedialog.asksaveasfilename(
        defaultextension=self.image_history[self.current_image_id]['extension_name'],
        initialfile=self.image_history[self.current_image_id]['reference_name'] + f"_{self.current_image_id}",
        filetypes=[("All files", "*.*")],
        title="Save an image"
    )
    if file_path:
        try:
            image_to_be_saved = self.apply_settings(self.current_image_id, 'actual_frame')
            image_to_be_saved.save(file_path)
            self.show_success_popup("Image saved successfully!")
        except Exception as e:
            self.show_error_popup(f"Failed to save image: {e}")