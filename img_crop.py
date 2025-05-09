def interrupt_crop(self, event):
    try:
        self.canvas.delete(self.figure)
        self.figure = None
        self.canvas.configure(cursor="arrow")
    except:
        pass
    
def start_selection(self, event):
    if event.state & 0x4:  # Check if Ctrl key is held
        self.canvas.configure(cursor="crosshair")
        self.start_x = event.x
        self.start_y = event.y
        
        # Default: Create a rectangle-like polygon
        self.figure = self.canvas.create_polygon(
            self.start_x, self.start_y,
            self.start_x, self.start_y,
            self.start_x, self.start_y,
            self.start_x, self.start_y,
            outline="green",
            fill="black", 
            stipple="gray50",
            width=2,
            dash=(5, 5),
        )
    else:
        self.canvas.delete(self.figure)
        self.figure = None

    

def update_selection(self, event):
    if event.state & 0x4:
        self.canvas.coords(
            self.figure,
            self.start_x, self.start_y,
            self.start_x, event.y,
            event.x, event.y,
            event.x, self.start_y,
        )
    else:
        self.canvas.delete(self.figure)
        self.figure = None


def finalize_selection(self, event):
    if event.state & 0x4:
        if self.figure:
            # Get bounding box for the polygon
            coords = self.canvas.coords(self.figure)
            selection_x0, selection_y0 = coords[0], coords[1]
            selection_x1, selection_y1 = coords[4], coords[5]

            # Sort coordinates (always left-top to right-bottom)
            selection_x0, selection_x1 = sorted([selection_x0, selection_x1])
            selection_y0, selection_y1 = sorted([selection_y0, selection_y1])

            # Get image position (centered)
            image_canvas_x, image_canvas_y = self.canvas.coords(self.image_container)

            # Current displayed image size
            image_width = self.placeholder_image.width
            image_height = self.placeholder_image.height

            # Calculate top-left corner of image on canvas
            image_x0 = image_canvas_x - image_width / 2
            image_y0 = image_canvas_y - image_height / 2

            # Relative selection within the image
            rel_x0 = (selection_x0 - image_x0) / image_width
            rel_y0 = (selection_y0 - image_y0) / image_height
            rel_x1 = (selection_x1 - image_x0) / image_width
            rel_y1 = (selection_y1 - image_y0) / image_height

            # Clamp between 0 and 1
            rel_x0 = max(0, min(1, rel_x0))
            rel_y0 = max(0, min(1, rel_y0))
            rel_x1 = max(0, min(1, rel_x1))
            rel_y1 = max(0, min(1, rel_y1))

            # Map relative coords to original (non-zoomed) image
            original_image = self.apply_settings(self.current_image_id, reference='actual_frame')
            orig_width, orig_height = original_image.size

            crop_x0 = int(rel_x0 * orig_width)
            crop_y0 = int(rel_y0 * orig_height)
            crop_x1 = int(rel_x1 * orig_width)
            crop_y1 = int(rel_y1 * orig_height)

            # Sanity check
            if crop_x0 >= crop_x1 or crop_y0 >= crop_y1:
                return

            # Crop
            cropped_image = original_image.crop((crop_x0, crop_y0, crop_x1, crop_y1))

            self.canvas.delete(self.figure)
            self.figure = None
    
            # Save the cropped image to history
            self.build_history(cropped_image, initial=True)
    else:
        if self.figure:
            self.canvas.delete(self.figure)
            
        self.figure = None
    
    self.canvas.configure(cursor="arrow")