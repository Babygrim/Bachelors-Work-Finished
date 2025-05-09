from constants import DEBUG
import time

def reset_scale(self):
    set_up_image = self.apply_settings(self.current_image_id, reference='actual_frame')
    self.placeholder_image, _ = self.resize_image(set_up_image, frame_ref=self.main_frame)
    self.image_history[self.current_image_id]['visible_frame_size'] = f"{self.placeholder_image.size[0]}x{self.placeholder_image.size[1]}"
    self.image_history[self.current_image_id]['placeholder_frame'] = self.placeholder_image
    self.image_history[self.current_image_id]['scale'] = self.image_history[self.current_image_id]['initial_scale']
    self.update_scale(self.image_history[self.current_image_id]['initial_scale'] * 100)
    self.display_on_canvas(self.placeholder_image, initial=True)
    
    if DEBUG:
        self.update_overlay_text()

def update_scroll_region(self):
    bbox = self.canvas.bbox(self.image_container)
    if bbox:
        self.canvas.config(scrollregion=bbox)
      
def zoom_slider(self, value):
    factor = 1 + self.zoom_factor if value / 100 > self.image_history[self.current_image_id]['scale'] else 1 - self.zoom_factor
    now = time.time()

    checker1 = value / 100 != self.scale_slider.cget('to') / 100 and value / 100 != self.scale_slider.cget('from_') / 100
    checker2 = now - self.last_zoomed > 0.05
    
    if not checker2:
        self.root.after_cancel(self.zoom_slider)
    
    if checker1 and checker2:
        coords = self.canvas.coords(self.image_container)
        self.modify_image(values={}, function=lambda in_image: self.apply_zoom(in_image, coords[0], coords[1], factor), text_value="", type=None)
    
def zoom(self, event):
    # Determine zoom direction
    factor = 1 + self.zoom_factor if event.delta > 0 else 1 - self.zoom_factor
    now = time.time()
    
    checker1 = self.image_history[self.current_image_id]['scale'] < self.scale_slider.cget('to') / 100 and event.delta > 1
    checker2 = self.image_history[self.current_image_id]['scale'] > self.scale_slider.cget('from_') / 100 and event.delta < 1
    checker3 = now - self.last_zoomed > 0.05
    
    if (checker1 or checker2) and checker3:
        self.modify_image(values={}, function=lambda in_image: self.apply_zoom(in_image, event.x, event.y, factor), text_value="", type=None)

def apply_zoom(self, in_image, center_x, center_y, factor):
    bbox = self.canvas.bbox(self.image_container)
    if bbox is None:
        return

    x0, y0, x1, y1 = bbox
    image_width = x1 - x0
    image_height = y1 - y0

    if image_width == 0 or image_height == 0:
        return

    # CENTER (because of anchor='center')
    center_x_image = (x0 + x1) / 2
    center_y_image = (y0 + y1) / 2

    # Mouse position relative to image center
    rel_x = (center_x - center_x_image) / image_width
    rel_y = (center_y - center_y_image) / image_height

    # Update the scale
    current_value = self.image_history[self.current_image_id]['scale'] * 100
    new_value = current_value * factor

    min_scale = self.scale_slider.cget('from_')
    max_scale = self.scale_slider.cget('to')
    new_value = max(min_scale, min(max_scale, new_value))

    self.update_scale(new_value)
    self.image_history[self.current_image_id]['scale'] = new_value / 100

    # Resize the image
    resized_image, _ = self.resize_image(
        in_image, 
        new_width=in_image.width * self.image_history[self.current_image_id]['scale'], 
        new_height=in_image.height * self.image_history[self.current_image_id]['scale']
    )

    self.image_history[self.current_image_id]['visible_frame_size'] = f"{resized_image.size[0]}x{resized_image.size[1]}"
    self.image_history[self.current_image_id]['placeholder_frame'] = resized_image
    self.placeholder_image = resized_image

    if DEBUG:
        self.update_overlay_text()

    self.display_on_canvas(resized_image, initial=False)

    new_width = resized_image.width
    new_height = resized_image.height

    # Recalculate new center
    new_center_x_image = center_x - rel_x * new_width
    new_center_y_image = center_y - rel_y * new_height

    # Move image so its center is at (new_center_x_image, new_center_y_image)
    self.canvas.coords(self.image_container, new_center_x_image, new_center_y_image)

    self.keep_image_in_bounds()
    self.update_scroll_region()

def start_drag(self, event):
    self.image_history[self.current_image_id]['drag_data']["x"] = event.x
    self.image_history[self.current_image_id]['drag_data']["y"] = event.y
    if DEBUG:
        self.update_overlay_text()

def do_drag(self, event):
    self.canvas.configure(cursor='hand2')
    dx = event.x - self.image_history[self.current_image_id]['drag_data']["x"]
    dy = event.y - self.image_history[self.current_image_id]['drag_data']["y"]
    if DEBUG:
        self.update_overlay_text()

    self.image_history[self.current_image_id]['drag_data']["x"] = event.x
    self.image_history[self.current_image_id]['drag_data']["y"] = event.y

    self.move_image(dx, dy)
    self.canvas.configure(cursor='arrow')

def move_image(self, dx, dy):
    self.canvas.configure(cursor='hand2')
    bbox = self.canvas.bbox(self.image_container)
    if bbox is None:
        return
    x0, y0, x1, y1 = bbox
    canvas_width = self.canvas.winfo_width()
    canvas_height = self.canvas.winfo_height()

    # Width and height of the image
    image_width = x1 - x0
    image_height = y1 - y0

    # Movement restrictions along x-axis
    if image_width <= canvas_width:
        dx = 0  # Image smaller than canvas, do not move horizontally
    else:
        if x0 + dx > 0:   # Would move image past left border
            dx = -x0
        elif x1 + dx < canvas_width:  # Would move image past right border
            dx = canvas_width - x1

    # Movement restrictions along y-axis
    if image_height <= canvas_height:
        dy = 0  # Image smaller than canvas, do not move vertically
    else:
        if y0 + dy > 0:  # Would move image past top border
            dy = -y0
        elif y1 + dy < canvas_height:  # Would move image past bottom border
            dy = canvas_height - y1

    self.canvas.move(self.image_container, dx, dy)
    coords = self.canvas.coords(self.image_container)
    self.image_history[self.current_image_id]["anchor_data"] = {'x': round(coords[0], 3), 'y': round(coords[1], 3)}
    
    if DEBUG:
        self.update_overlay_text()
    self.canvas.configure(cursor='arrow')
    
def keep_image_in_bounds(self):
    bbox = self.canvas.bbox(self.image_container)
    if bbox is None:
        return

    x0, y0, x1, y1 = bbox
    canvas_width = self.canvas.winfo_width()
    canvas_height = self.canvas.winfo_height()

    dx = dy = 0

    image_width = x1 - x0
    image_height = y1 - y0

    # If image smaller than canvas, center it
    if image_width < canvas_width:
        dx = (canvas_width - image_width) / 2 - x0
    else:
        if x0 > 0:
            dx = -x0
        elif x1 < canvas_width:
            dx = canvas_width - x1

    if image_height < canvas_height:
        dy = (canvas_height - image_height) / 2 - y0
    else:
        if y0 > 0:
            dy = -y0
        elif y1 < canvas_height:
            dy = canvas_height - y1

    self.canvas.move(self.image_container, dx, dy)
    coords = self.canvas.coords(self.image_container)
    self.image_history[self.current_image_id]["anchor_data"] = {'x': round(coords[0], 3), 'y': round(coords[1], 3)}
    
    if DEBUG:
        self.update_overlay_text()
