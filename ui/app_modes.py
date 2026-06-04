def turnDEBUGmodeOn(self):
    # create borders around frames
    self.image_toolbar.configure(fg_color='grey', border_width=3, border_color="red")
    self.photo_frame_extra.configure(fg_color='grey', border_width=3, border_color="red")
    self.canvas_wrapper.configure(fg_color='grey', border_width=3, border_color="red" )
    self.top_toolbar.configure(fg_color='grey', border_width=3, border_color="red" )
    self.main_frame.configure(fg_color='grey', border_width=3, border_color="red" )
    self.module_toolframe.configure(fg_color='grey', border_width=3, border_color="red" )
    
def turnDEBUGmodeOff(self):
    # change frame background color
    self.top_toolbar.configure(fg_color='#20374c')
    self.image_toolbar.configure(fg_color='#20374c')
    self.module_toolframe.configure(fg_color='#20374c')