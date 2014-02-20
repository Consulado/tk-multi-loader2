# Copyright (c) 2013 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

import sgtk
from sgtk.platform.qt import QtCore, QtGui

# import the shotgun_model module from the shotgun utils framework
shotgun_model = sgtk.platform.import_framework("tk-framework-shotgunutils", "shotgun_model") 
ShotgunModel = shotgun_model.ShotgunModel 

class SgPublishTypeModel(ShotgunModel):
    """
    This model represents the data which is displayed inside one of the treeview tabs
    on the left hand side.
    """
    
    SORT_KEY_ROLE = QtCore.Qt.UserRole + 102        # holds a sortable key
    DISPLAY_NAME_ROLE = QtCore.Qt.UserRole + 103    # holds the display name for the node
    HANDLED_BY_HOOK_ROLE = QtCore.Qt.UserRole + 104 # hooks know how to process this type
    
    FOLDERS_ITEM_TEXT = "Folders"
    
    def __init__(self, parent, overlay_parent_widget, action_manager):
        """
        Constructor
        """
        # folder icon
        ShotgunModel.__init__(self, parent, overlay_parent_widget, download_thumbs=False)
        
        self._action_manager = action_manager
        
        # specify sort key
        self.setSortRole(SgPublishTypeModel.SORT_KEY_ROLE)
                
        # now set up the model.        
        # first figure out which fields to get from shotgun
        app = sgtk.platform.current_bundle()
        publish_entity_type = sgtk.util.get_published_file_entity_type(app.sgtk)
        
        if publish_entity_type == "PublishedFile":
            publish_type_field = "PublishedFileType"
        else:
            publish_type_field = "TankType"
                
        # slight hack: we pass in the checksum of the actions listing (the hook)
        # as a field to the model. This will force the caching to take the hook code
        # into account, ensuring that the HANDLED_BY_HOOK_ROLE is handled correcty
        # across different environments
        ShotgunModel._load_data(self, 
                               entity_type=publish_type_field, 
                               filters=[], 
                               hierarchy=["code"], 
                               fields=["code","description","id", self._action_manager.get_actions_chksum()],
                               order=[])
        
        # and finally ask model to refresh itself
        self._refresh_data()

    def select_none(self):
        """
        Deselect all types
        """
        for idx in range(self.rowCount()):
            item = self.item(idx)
            # ignore special case folders item
            if item.text() != SgPublishTypeModel.FOLDERS_ITEM_TEXT:
                item.setCheckState(QtCore.Qt.Unchecked)
    
    def select_all(self):
        """
        Select all types
        """
        for idx in range(self.rowCount()):
            item = self.item(idx)
            item.setCheckState(QtCore.Qt.Checked)
        
    def select_compatible(self):
        """
        Select compatible types
        """
        for idx in range(self.rowCount()):
            item = self.item(idx)
            # ignore special case folders item
            if item.text() != SgPublishTypeModel.FOLDERS_ITEM_TEXT:
                if item.data(SgPublishTypeModel.HANDLED_BY_HOOK_ROLE):         
                    item.setCheckState(QtCore.Qt.Checked)
                else:
                    item.setCheckState(QtCore.Qt.Unchecked)

    def get_show_folders(self):
        """
        Returns true if the special Folders
        entry is ticked, false otherwise
        """
        for idx in range(self.rowCount()):
            item = self.item(idx)
            
            # ignore special case folders item
            if item.text() != SgPublishTypeModel.FOLDERS_ITEM_TEXT:
                continue            
            
            if item.checkState() == QtCore.Qt.Checked:
                return True
        
        return False
    
    def get_selected_types(self):
        """
        Returns all the sg type ids that are currently selected. 
        
        :returns: a list of type ids (ints)
        """
        type_ids = []
        for idx in range(self.rowCount()):
            item = self.item(idx)
            
            # ignore special case folders item
            if item.text() == SgPublishTypeModel.FOLDERS_ITEM_TEXT:
                continue            
            
            if item.checkState() == QtCore.Qt.Checked:
                # get the shotgun id
                sg_type_id = item.data(ShotgunModel.SG_DATA_ROLE).get("id")
                type_ids.append(sg_type_id)
        return type_ids
        
        
    def set_active_types(self, type_aggregates):
        """
        Specifies which types are currently active. Also adjust the sort role,
        so that the view puts enabled items at the top of the list!
        
        :param type_aggregates: dict keyed by type id with value being the number of 
                                of occurances of that type in the currently displayed result
        """
        for idx in range(self.rowCount()):
            
            item = self.item(idx)
            
            # ignore special folders item
            if item.text() == SgPublishTypeModel.FOLDERS_ITEM_TEXT:
                continue
            
            sg_type_id = item.data(ShotgunModel.SG_DATA_ROLE).get("id")            
            display_name = item.data(SgPublishTypeModel.DISPLAY_NAME_ROLE)
            is_blue = item.data(SgPublishTypeModel.HANDLED_BY_HOOK_ROLE)
            
            if sg_type_id in type_aggregates:
                
                # this type is in the active list
                if is_blue:
                    # blue items are up the very top
                    item.setData("a_%s" % display_name, SgPublishTypeModel.SORT_KEY_ROLE)
                else:
                    # enabled but non-blue come after
                    item.setData("b_%s" % display_name, SgPublishTypeModel.SORT_KEY_ROLE)
                
                item.setEnabled(True)
                
                # display name with aggregate summary
                item.setText("%s (%d)" % (display_name, type_aggregates[sg_type_id]))
                
            else:
                item.setEnabled(False)
                if is_blue:
                    item.setData("c_%s" % display_name, SgPublishTypeModel.SORT_KEY_ROLE)
                else:
                    item.setData("d_%s" % display_name, SgPublishTypeModel.SORT_KEY_ROLE)
                # disply name with no aggregate
                item.setText(display_name)
                
        # and ask the model to resort itself 
        self.sort(0)
            
    ############################################################################################
    # subclassed methods
            
    def _load_external_data(self):
        """
        Called whenever the model needs to be rebuilt from scratch. This is called prior 
        to any shotgun data is added to the model. This makes it possible for deriving classes
        to add custom data to the model in a very flexible fashion. Such data will not be 
        cached by the ShotgunModel framework.
        """
        
        # process the folder data and add that to the model. Keep local references to the 
        # items to keep the GC happy.
        
        self._folder_items = []        
        item = QtGui.QStandardItem(SgPublishTypeModel.FOLDERS_ITEM_TEXT)
        item.setCheckable(True)
        item.setForeground( QtGui.QBrush( QtGui.QColor("#619DE0") ) )
        item.setCheckState(QtCore.Qt.Checked)
        item.setToolTip("This filter controls the <i>folder objects</i>. "
                        "If you are using the 'Show items in subfolders' mode, it can "
                        "sometimes be useful to hide folders and only see publishes.")        
        self.appendRow(item)
        self._folder_items.append(item)
            
            
    def _populate_default_thumbnail(self, item):
        """
        Called whenever an item is originally born, either because a shotgun query returned it
        or because it was loaded as part of a cache load from disk. This method will by default
        set up all brand new fresh items with an empty thumbail.
        
        Later on, if the model was instantiated with the download_thumbs parameter set to True,
        the standard 'image' field thumbnail will be automatically downloaded for all items (or
        picked up from local cache if possible). When these real thumbnails arrive, the
        _populate_thumbnail() method will be called.
        
        This method can be useful if you want to control both the visual state of an entity which
        does not have a thumbnail in Shotgun and the state before a thumbnail has been downloaded.
        
        :param item: QStandardItem that is about to be added to the model. This has been primed
                     with the standard settings that the ShotgunModel handles.        
        """
        ShotgunModel._populate_default_thumbnail(self, item)
        # implement this method as a way to be able to interact with items
        # as they are born, either from the cache or from SG
        
        # When items are born they are all disabled by default
        item.setEnabled(False)
            
    def _populate_item(self, item, sg_data):
        """
        Whenever an item is constructed, this methods is called. It allows subclasses to intercept
        the construction of a QStandardItem and add additional metadata or make other changes
        that may be useful. Nothing needs to be returned.
        
        :param item: QStandardItem that is about to be added to the model. This has been primed
                     with the standard settings that the ShotgunModel handles.
        :param sg_data: Shotgun data dictionary that was received from Shotgun given the fields
                        and other settings specified in load_data()
        """
        sg_code = sg_data.get("code")
        if sg_code is None:
            sg_name_formatted = "Unnamed"
        else:
            sg_name_formatted = sg_code.capitalize()
        
        item.setData(sg_name_formatted, SgPublishTypeModel.DISPLAY_NAME_ROLE)
        item.setCheckable(True)
        
        if len(self._action_manager.get_actions_for_type(sg_code)) > 0:
            # there are actions for this file type!
            # check it and highlight it
            item.setCheckState(QtCore.Qt.Checked)
            item.setForeground( QtGui.QBrush( QtGui.QColor("#619DE0") ) )
            item.setData(True, SgPublishTypeModel.HANDLED_BY_HOOK_ROLE)
            item.setToolTip("The <b style='color: #619DE0'>blue color</b> indicates that this "
                            "type of publish can be loaded into the current application.")
        else:
            # current hooks do not know what to do with this type
            # -- uncheck it
            item.setCheckState(QtCore.Qt.Unchecked)
            item.setToolTip("Publishes of this type are unchecked by default because they cannot "
                            "be loaded into the current application.")
