# Copyright (c) 2015 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Hook that loads defines all the available actions, broken down by publish type.
"""

import glob
import os
import re
from pprint import pprint
import maya.cmds as cmds
import pymel.core as pm
import maya.mel as mel
import sgtk
import platform

from tank_vendor import six

HookBaseClass = sgtk.get_hook_baseclass()


class MayaActions(HookBaseClass):

    ##############################################################################################################
    # public interface - to be overridden by deriving classes

    def generate_actions(self, sg_publish_data, actions, ui_area):
        """
        Returns a list of action instances for a particular publish.
        This method is called each time a user clicks a publish somewhere in the UI.
        The data returned from this hook will be used to populate the actions menu for a publish.

        The mapping between Publish types and actions are kept in a different place
        (in the configuration) so at the point when this hook is called, the loader app
        has already established *which* actions are appropriate for this object.

        The hook should return at least one action for each item passed in via the
        actions parameter.

        This method needs to return detailed data for those actions, in the form of a list
        of dictionaries, each with name, params, caption and description keys.

        Because you are operating on a particular publish, you may tailor the output
        (caption, tooltip etc) to contain custom information suitable for this publish.

        The ui_area parameter is a string and indicates where the publish is to be shown.
        - If it will be shown in the main browsing area, "main" is passed.
        - If it will be shown in the details area, "details" is passed.
        - If it will be shown in the history area, "history" is passed.

        Please note that it is perfectly possible to create more than one action "instance" for
        an action! You can for example do scene introspection - if the action passed in
        is "character_attachment" you may for example scan the scene, figure out all the nodes
        where this object can be attached and return a list of action instances:
        "attach to left hand", "attach to right hand" etc. In this case, when more than
        one object is returned for an action, use the params key to pass additional
        data into the run_action hook.

        :param sg_publish_data: Shotgun data dictionary with all the standard publish fields.
        :param actions: List of action strings which have been defined in the app configuration.
        :param ui_area: String denoting the UI Area (see above).
        :returns List of dictionaries, each with keys name, params, caption and description
        """
        app = self.parent
        app.log_debug(
            "Generate actions called for UI element %s. "
            "Actions: %s. Publish Data: %s" % (ui_area, actions, sg_publish_data)
        )

        action_instances = []

        if "reference" in actions:
            action_instances.append(
                {
                    "name": "reference",
                    "params": None,
                    "caption": "Create Reference",
                    "description": "This will add the item to the scene as a standard reference.",
                }
            )

        if "import" in actions:
            action_instances.append(
                {
                    "name": "import",
                    "params": None,
                    "caption": "Import into Scene",
                    "description": "This will import the item into the current scene.",
                }
            )

        if "texture_node" in actions:
            action_instances.append(
                {
                    "name": "texture_node",
                    "params": None,
                    "caption": "Create Texture Node",
                    "description": "Creates a file texture node for the selected item..",
                }
            )

        if "udim_texture_node" in actions:
            # Special case handling for Mari UDIM textures as these currently only load into
            # Maya 2015 in a nice way!
            if self._get_maya_version() >= 2015:
                action_instances.append(
                    {
                        "name": "udim_texture_node",
                        "params": None,
                        "caption": "Create Texture Node",
                        "description": "Creates a file texture node for the selected item..",
                    }
                )

        if "image_plane" in actions:
            action_instances.append(
                {
                    "name": "image_plane",
                    "params": None,
                    "caption": "Create Image Plane",
                    "description": "Creates an image plane for the selected item..",
                }
            )

        return action_instances

    def execute_multiple_actions(self, actions):
        """
        Executes the specified action on a list of items.

        The default implementation dispatches each item from ``actions`` to
        the ``execute_action`` method.

        The ``actions`` is a list of dictionaries holding all the actions to execute.
        Each entry will have the following values:

            name: Name of the action to execute
            sg_publish_data: Publish information coming from Shotgun
            params: Parameters passed down from the generate_actions hook.

        .. note::
            This is the default entry point for the hook. It reuses the ``execute_action``
            method for backward compatibility with hooks written for the previous
            version of the loader.

        .. note::
            The hook will stop applying the actions on the selection if an error
            is raised midway through.

        :param list actions: Action dictionaries.
        """
        actions_result = {}
        for single_action in actions:
            name = single_action["name"]
            sg_publish_data = single_action["sg_publish_data"]
            params = single_action["params"]
            res = self.execute_action(name, params, sg_publish_data)

            if res is None:
                continue

            if not actions_result.get(name):
                actions_result[name] = [res]
            else:
                actions_result[name].append(res)

        if actions_result:
            self._check_and_import_shaders(actions_result)

    def _check_and_import_shaders(self, data):
        engine = sgtk.platform.current_engine()
        sg = engine.shotgun
        context = engine.context

        if not self._context_type_is("Shot") and self._step_name_in(["lighting"]):
            return

        tk_consuladoutils = self.load_framework("tk-framework-consuladoutils_v0.x.x")
        consulado_globals = tk_consuladoutils.import_module("shotgun_globals")
        maya_utils = tk_consuladoutils.import_module("maya_utils")
        consulado_model = tk_consuladoutils.import_module("shotgun_model")

        sg_node_name = consulado_globals.get_custom_entity_by_alias("node")
        sg_node_type_name = consulado_globals.get_custom_entity_by_alias("node_type")
        node_x_node = "custom_entity05_sg_upstream_node_dependency_custom_entity05s"
        node_fields = [
            "project",
            "id",
            "code",
            "sg_link",
            "sg_node_type",
            "sg_downstream_node_dependency",
            "sg_upstream_node_dependency",
            "sg_published_files",
            node_x_node,
        ]
        publish_fields = [
            "project",
            "id",
            "entity",
            "published_file_type",
            "version_number",
            "path",
        ]
        local_data = {}
        for action, asset_result in data.items():
            for asset in asset_result:
                Nodes = consulado_model.EntityIter(
                    sg_node_name, node_fields, context, sg
                )
                published_files = consulado_model.EntityIter(
                    "PublishedFile", publish_fields, context, sg
                )
                geos = [t for t in asset if t.nodeType() in ("transform")]
                maya_asset = maya_utils.MayaAsset(geos)

                for geo_node in maya_asset:
                    c_id = geo_node.cNodeId.get()
                    node = Nodes.add_new_entity()
                    node.id = c_id
                    node.entity_filter = [["id", "is", node.id]]
                    node.load()

                    upstreams = getattr(node, node_x_node)
                    if not upstreams:
                        continue

                    last_publish = None
                    for con in upstreams:
                        entity_filter = [
                            ["entity", "is", con],
                            [
                                "published_file_type",
                                "is",
                                {"type": "PublishedFileType", "id": 135},
                            ],
                        ]
                        published_files.load(entity_filter)
                        for publish in published_files:
                            if (
                                last_publish is None
                                or last_publish.version_number < publish.version_number
                            ):
                                last_publish = publish
                                continue
                        if last_publish is None:
                            continue
                        path_data = last_publish.path
                        pprint(path_data)
                        local_path = "{}.ma".format(
                            path_data.get(
                                "local_path_{}".format(platform.system().lower()), ""
                            )
                        )
                        if local_path == ".ma":
                            continue

                        if local_data.get(local_path) is None:
                            local_data[local_path] = []

                        local_data[local_path].append(geo_node)

        with maya_utils.ShaderIter(local_data=local_data) as shader_iter:
            shader_iter.apply()

    def execute_action(self, name, params, sg_publish_data):
        """
        Execute a given action. The data sent to this be method will
        represent one of the actions enumerated by the generate_actions method.

        :param name: Action name string representing one of the items returned by generate_actions.
        :param params: Params data, as specified by generate_actions.
        :param sg_publish_data: Shotgun data dictionary with all the standard publish fields.
        :returns: No return value expected.
        """
        app = self.parent
        app.log_debug(
            "Execute action called for action %s. "
            "Parameters: %s. Publish Data: %s" % (name, params, sg_publish_data)
        )

        # resolve path
        # toolkit uses utf-8 encoded strings internally and Maya API expects unicode
        # so convert the path to ensure filenames containing complex characters are supported
        path = six.ensure_str(self.get_publish_path(sg_publish_data))

        asset_data = None
        if name == "reference":
            asset_data = self._create_reference(path, sg_publish_data)

        if name == "import":
            asset_data = self._do_import(path, sg_publish_data)

        if name == "texture_node":
            self._create_texture_node(path, sg_publish_data)

        if name == "udim_texture_node":
            self._create_udim_texture_node(path, sg_publish_data)

        if name == "image_plane":
            self._create_image_plane(path, sg_publish_data)

        return asset_data

    ##############################################################################################################
    # helper methods which can be subclassed in custom hooks to fine tune the behaviour of things

    @staticmethod
    def _context_type_is(t):
        engine = sgtk.platform.current_engine()
        context = engine.context
        return context.entity.get("type", "") == t

    @staticmethod
    def _step_name_in(steps):
        engine = sgtk.platform.current_engine()
        context = engine.context
        return context.step.get("name", "").lower() in steps

    def _create_reference(self, path, sg_publish_data):
        """
        Create a reference with the same settings Maya would use
        if you used the create settings dialog.

        :param path: Path to file.
        :param sg_publish_data: Shotgun data dictionary with all the standard publish fields.
        """
        if not os.path.exists(path):
            raise Exception("File not found on disk - '%s'" % path)

        # make a name space out of entity name + publish name
        # e.g. bunny_upperbody
        # namespace = "%s %s" % (
        #     sg_publish_data.get("entity").get("name"),
        #     sg_publish_data.get("name"),
        # )
        # namespace = namespace.replace(" ", "_")
        namespace = sg_publish_data.get("name", "").replace(" ", "_")

        # Create a default group
        asset_name = sg_publish_data.get("name", "").split(".")[0]
        asset_group = pm.group(name=asset_name, empty=True)
        render_group = pm.group(name="render", empty=True)
        pm.parent(render_group, asset_group)

        # Now create the reference object in Maya.
        nodes = pm.createReference(
            path, loadReferenceDepth="all", namespace=namespace, returnNewNodes=True
        )

        if not self._context_type_is("Shot") and self._step_name_in(["lighting"]):
            return nodes

        # Add the geometries nodes into render group
        for n in nodes:
            if n.nodeType() not in ("transform"):
                continue
            n.setParent(render_group)

        return nodes

    def _do_import(self, path, sg_publish_data):
        """
        Create a reference with the same settings Maya would use
        if you used the create settings dialog.

        :param path: Path to file.
        :param sg_publish_data: Shotgun data dictionary with all the standard publish fields.
        """
        if not os.path.exists(path):
            raise Exception("File not found on disk - '%s'" % path)

        # make a name space out of entity name + publish name
        # e.g. bunny_upperbody
        # namespace = "%s %s" % (
        #     sg_publish_data.get("entity").get("name"),
        #     sg_publish_data.get("name"),
        # )
        namespace = sg_publish_data.get("name", "").replace(" ", "_")
        # namespace = namespace.replace(" ", "_")

        # perform a more or less standard maya import, putting all nodes brought in into a specific namespace
        # cmds.file(
        #     path,
        #     i=True,
        #     renameAll=True,
        #     namespace=namespace,
        #     loadReferenceDepth="all",
        #     preserveReferences=True,
        # )
        # Create a default group
        asset_name = sg_publish_data.get("name", "").split(".")[0]
        asset_group = pm.group(name=asset_name, empty=True)
        render_group = pm.group(name="render", empty=True)
        pm.parent(render_group, asset_group)

        nodes = pm.importFile(path, loadReferenceDepth="all", returnNewNodes=True)

        if not self._context_type_is("Shot") and self._step_name_in(["lighting"]):
            return nodes

        for n in nodes:
            if n.nodeType() not in ("transform"):
                continue
            pm.parent(n, render_group)

        return nodes

    def _create_texture_node(self, path, sg_publish_data):
        """
        Create a file texture node for a texture

        :param path:             Path to file.
        :param sg_publish_data:  Shotgun data dictionary with all the standard publish fields.
        :returns:                The newly created file node
        """
        file_node = cmds.shadingNode("file", asTexture=True)
        cmds.setAttr("%s.fileTextureName" % file_node, path, type="string")
        return file_node

    def _create_udim_texture_node(self, path, sg_publish_data):
        """
        Create a file texture node for a UDIM (Mari) texture

        :param path:             Path to file.
        :param sg_publish_data:  Shotgun data dictionary with all the standard publish fields.
        :returns:                The newly created file node
        """
        # create the normal file node:
        file_node = self._create_texture_node(path, sg_publish_data)
        if file_node:
            # path is a UDIM sequence so set the uv tiling mode to 3 ('UDIM (Mari)')
            cmds.setAttr("%s.uvTilingMode" % file_node, 3)
            # and generate a preview:
            mel.eval("generateUvTilePreview %s" % file_node)
        return file_node

    def _create_image_plane(self, path, sg_publish_data):
        """
        Create a file texture node for a UDIM (Mari) texture

        :param path: Path to file.
        :param sg_publish_data: Shotgun data dictionary with all the standard
            publish fields.
        :returns: The newly created file node
        """

        app = self.parent
        has_frame_spec = False

        # replace any %0#d format string with a glob character. then just find
        # an existing frame to use. example %04d => *
        frame_pattern = re.compile("(%0\dd)")
        frame_match = re.search(frame_pattern, path)
        if frame_match:
            has_frame_spec = True
            frame_spec = frame_match.group(1)
            glob_path = path.replace(frame_spec, "*")
            frame_files = glob.glob(glob_path)
            if frame_files:
                path = frame_files[0]
            else:
                app.logger.error(
                    "Could not find file on disk for published file path %s" % (path,)
                )
                return

        # create an image plane for the supplied path, visible in all views
        (img_plane, img_plane_shape) = cmds.imagePlane(
            fileName=path, showInAllViews=True
        )
        app.logger.debug("Created image plane %s with path %s" % (img_plane, path))

        if has_frame_spec:
            # setting the frame extension flag will create an expression to use
            # the current frame.
            cmds.setAttr("%s.useFrameExtension" % (img_plane_shape,), 1)

    def _get_maya_version(self):
        """
        Determine and return the Maya version as an integer

        :returns:    The Maya major version
        """
        if not hasattr(self, "_maya_major_version"):
            self._maya_major_version = 0
            # get the maya version string:
            maya_ver = cmds.about(version=True)
            # handle a couple of different formats: 'Maya XXXX' & 'XXXX':
            if maya_ver.startswith("Maya "):
                maya_ver = maya_ver[5:]
            # strip of any extra stuff including decimals:
            major_version_number_str = maya_ver.split(" ")[0].split(".")[0]
            if major_version_number_str and major_version_number_str.isdigit():
                self._maya_major_version = int(major_version_number_str)
        return self._maya_major_version
