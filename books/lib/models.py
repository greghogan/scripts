class LibraryNode:
    def __init__(self, folder_name, full_path):
        self.folder_name = folder_name
        self.full_path = full_path
        self.files = []
        self.children = {}
        self.ddc_def = None

    def add_file(self, file_info):
        self.files.append(file_info)
