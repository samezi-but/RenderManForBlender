# ##### BEGIN MIT LICENSE BLOCK #####
#
# Copyright (c) 2015 Brian Savery
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
#
# ##### END MIT LICENSE BLOCK #####

import bpy
import _cycles
from bpy.app.handlers import persistent

import xml.etree.ElementTree as ET

import tempfile
import nodeitems_utils
import shutil

from bpy.props import *
from nodeitems_utils import NodeCategory, NodeItem

from .shader_parameters import class_generate_properties
from .shader_parameters import node_add_inputs
from .shader_parameters import node_add_outputs
from .shader_parameters import socket_map
from .shader_parameters import txmake_options
from .util import args_files_in_path
from .util import get_path_list
from .util import rib
from .util import debug
from .util import user_path
from .util import get_real_path
from .util import readOSO
from .cycles_convert import *

from operator import attrgetter, itemgetter
import os.path
from time import sleep

NODE_LAYOUT_SPLIT = 0.5

group_nodes = ['ShaderNodeGroup', 'NodeGroupInput', 'NodeGroupOutput']
# Default Types

# socket name corresponds to the param on the node
class RendermanSocket:
    ui_open = BoolProperty(name='UI Open', default=True)
    def get_pretty_name(self, node):
        if node.bl_idname in group_nodes:
            return self.name
        else: 
            return self.identifier

    def get_value(self, node):
        if node.bl_idname in group_nodes or not hasattr(node, self.name):
            return self.default_value
        else:
            return getattr(node, self.name)

    def draw_color(self, context, node):
        return (0.25, 1.0, 0.25, 1.0)

    def draw_value(self, context, layout, node):
        layout.prop(node, self.identifier)

    def draw(self, context, layout, node, text):
        if self.is_linked or self.is_output or self.hide_value:
            layout.label(self.get_pretty_name(node))
        elif node.bl_idname == "PxrOSLPatternNode":
            if hasattr(context.scene, "OSLProps"):
                oslProps = context.scene.OSLProps
                mat = context.object.active_material.name
                storageLocation = mat + node.name + self.name
                if hasattr(oslProps, storageLocation):
                    layout.prop(oslProps, storageLocation)
                # else:
                #    rebuild_OSL_nodes(context.scene, context)
        elif node.bl_idname in group_nodes:
            layout.prop(self, 'default_value', text=self.get_pretty_name(node), slider=True)
        else:
            layout.prop(node, self.name, text=self.get_pretty_name(node), slider=True)


class RendermanSocketInterface:
    def draw_color(self, context):
        return (0.25, 1.0, 0.25, 1.0)

    def draw(self, context, layout):
        layout.label(self.name)
    
    def from_socket(self, node, socket):
        if hasattr(self, 'default_value'):
            self.default_value = socket.get_value(node)
        self.name = socket.name
        
    
    def init_socket(self, node, socket, data_path):
        sleep(.01)
        socket.name = self.name
        if hasattr(self, 'default_value'):
            socket.default_value = self.default_value
        
        
# socket types (need this just for the ui_open)
class RendermanNodeSocketFloat(bpy.types.NodeSocketFloat, RendermanSocket):
    '''Renderman float input/output'''
    bl_idname = 'RendermanNodeSocketFloat'
    bl_label = 'Renderman Float Socket'
    
    default_value = FloatProperty()
    
    def draw_color(self, context, node):
        return (0.5, 0.5, 0.5, 1.0)

class RendermanNodeSocketInterfaceFloat(bpy.types.NodeSocketInterfaceFloat, RendermanSocketInterface):
    '''Renderman float input/output'''
    bl_idname = 'RendermanNodeSocketInterfaceFloat'
    bl_label = 'Renderman Float Socket'
    bl_socket_idname = 'RendermanNodeSocketFloat'

    default_value = FloatProperty()
    
    def draw_color(self, context):
        return (0.5, 0.5, 0.5, 1.0)

class RendermanNodeSocketInt(bpy.types.NodeSocketInt, RendermanSocket):
    '''Renderman int input/output'''
    bl_idname = 'RendermanNodeSocketInt'
    bl_label = 'Renderman Int Socket'
    
    default_value = IntProperty()
    
    def draw_color(self, context, node):
        return (1.0, 1.0, 1.0, 1.0)

class RendermanNodeSocketInterfaceInt(bpy.types.NodeSocketInterfaceInt, RendermanSocketInterface):
    '''Renderman float input/output'''
    bl_idname = 'RendermanNodeSocketInterfaceInt'
    bl_label = 'Renderman Int Socket'
    bl_socket_idname = 'RendermanNodeSocketInt'

    default_value = IntProperty()
    
    def draw_color(self, context):
        return (1.0, 1.0, 1.0, 1.0)
    
class RendermanNodeSocketString(bpy.types.NodeSocketString, RendermanSocket):
    '''Renderman string input/output'''
    bl_idname = 'RendermanNodeSocketString'
    bl_label = 'Renderman String Socket'
    default_value = StringProperty()

class RendermanNodeSocketStruct(bpy.types.NodeSocketString, RendermanSocket):
    '''Renderman struct input/output'''
    bl_idname = 'RendermanNodeSocketStruct'
    bl_label = 'Renderman Struct Socket'
    hide_value = True

class RendermanNodeSocketInterfaceStruct(bpy.types.NodeSocketInterfaceString, RendermanSocketInterface):
    '''Renderman struct input/output'''
    bl_idname = 'RendermanNodeSocketInterfaceStruct'
    bl_label = 'Renderman Struct Socket'
    bl_socket_idname = 'RendermanNodeSocketStruct'
    hide_value = True

class RendermanNodeSocketColor(bpy.types.NodeSocketColor, RendermanSocket):
    '''Renderman color input/output'''
    bl_idname = 'RendermanNodeSocketColor'
    bl_label = 'Renderman Color Socket'

    default_value = FloatVectorProperty(size=3,
                                   subtype="COLOR")
    def draw_color(self, context, node):
        return (1.0, 1.0, .5, 1.0)

class RendermanNodeSocketInterfaceColor(bpy.types.NodeSocketInterfaceColor, RendermanSocketInterface):
    '''Renderman color input/output'''
    bl_idname = 'RendermanNodeSocketInterfaceColor'
    bl_label = 'Renderman Color Socket'
    bl_socket_idname = 'RendermanNodeSocketColor'

    default_value = FloatVectorProperty(size=3,
                                   subtype="COLOR")

    def draw_color(self, context):
        return (1.0, 1.0, .5, 1.0)

class RendermanNodeSocketVector(RendermanSocket, bpy.types.NodeSocketVector):
    '''Renderman vector input/output'''
    bl_idname = 'RendermanNodeSocketVector'
    bl_label = 'Renderman Vector Socket'
    hide_value = True

    default_value = FloatVectorProperty(size=3,
                                        subtype="EULER")
    def draw_color(self, context, node):
        return (.25, .25, .75, 1.0)

class RendermanNodeSocketInterfaceVector(bpy.types.NodeSocketInterfaceVector, RendermanSocketInterface):
    '''Renderman color input/output'''
    bl_idname = 'RendermanNodeSocketInterfaceVector'
    bl_label = 'Renderman Vector Socket'
    bl_socket_idname = 'RendermanNodeSocketVector'
    hide_value = True

    default_value = FloatVectorProperty(size=3,
                                        subtype="EULER")

    def draw_color(self, context):
        return (.25, .25, .75, 1.0)

# Custom socket type for connecting shaders
class RendermanShaderSocket(bpy.types.NodeSocketShader, RendermanSocket):
    '''Renderman shader input/output'''
    bl_idname = 'RendermanShaderSocket'
    bl_label = 'Renderman Shader Socket'
    hide_value = True

# Custom socket type for connecting shaders
class RendermanShaderSocketInterface(bpy.types.NodeSocketInterfaceShader, RendermanSocketInterface):
    '''Renderman shader input/output'''
    bl_idname = 'RendermanShaderInterfaceSocket'
    bl_label = 'Renderman Shader Socket'
    bl_socket_idname = 'RendermanShaderSocket'
    hide_value = True


# Base class for all custom nodes in this tree type.
# Defines a poll function to enable instantiation.
class RendermanShadingNode(bpy.types.ShaderNode):
    bl_label = 'Output'

    def update_mat(self, mat):
        if self.renderman_node_type == 'bxdf' and self.outputs['Bxdf'].is_linked:
            mat.specular_color = [1, 1, 1]
            mat.diffuse_color = [1, 1, 1]
            mat.use_transparency = False
            mat.specular_intensity = 0
            mat.diffuse_intensity = 1

            if hasattr(self, "baseColor"):
                mat.diffuse_color = self.baseColor
            elif hasattr(self, "emitColor"):
                mat.diffuse_color = self.emitColor
            elif hasattr(self, "diffuseColor"):
                mat.diffuse_color = self.diffuseColor
            elif hasattr(self, "midColor"):
                mat.diffuse_color = self.midColor
            elif hasattr(self, "transmissionColor"):
                mat.diffuse_color = self.transmissionColor
            elif hasattr(self, "frontColor"):
                mat.diffuse_color = self.frontColor

            # specular intensity
            if hasattr(self, "specular"):
                mat.specular_intensity = self.specular
            elif hasattr(self, "SpecularGainR"):
                mat.specular_intensity = self.specularGainR
            elif hasattr(self, "reflectionGain"):
                mat.specular_intensity = self.reflectionGain

            # specular color
            if hasattr(self, "specularColor"):
                mat.specular_color = self.specularColor
            elif hasattr(self, "reflectionColor"):
                mat.specular_color = self.reflectionColor

            if self.bl_idname in ["PxrGlassBxdfNode", "PxrLMGlassBxdfNode"]:
                mat.use_transparency = True
                mat.alpha = .5

            if self.bl_idname == "PxrLMMetalBxdfNode":
                mat.diffuse_color = [0, 0, 0]
                mat.specular_intensity = 1
                mat.specular_color = self.specularColor
                mat.mirror_color = [1, 1, 1]

            elif self.bl_idname == "PxrLMPlasticBxdfNode":
                mat.specular_intensity = 1

    # all the properties of a shader will go here, also inputs/outputs
    # on connectable props will have the same name
    # node_props = None
    def draw_buttons(self, context, layout):
        self.draw_nonconnectable_props(context, layout, self.prop_names)
        if self.bl_idname == "PxrOSLPatternNode":
            layout.operator("node.refresh_osl_shader")

    def draw_buttons_ext(self, context, layout):
        self.draw_nonconnectable_props(context, layout, self.prop_names)

    def draw_nonconnectable_props(self, context, layout, prop_names):
        if self.bl_idname in ['PxrLayerPatternNode', 'PxrSurfaceBxdfNode']:
            col = layout.column(align=True)
            for prop_name in prop_names:
                if prop_name not in self.inputs:
                    for name in getattr(self, prop_name):
                        if name.startswith('enable'):
                            col.prop(self, name, text=prop_name.split('.')[-1])
                            break
            return

        if self.bl_idname == "PxrOSLPatternNode" or self.bl_idname == "PxrSeExprPatternNode":
            prop = getattr(self, "codetypeswitch")
            layout.prop(self, "codetypeswitch")
            if getattr(self, "codetypeswitch") == 'INT':
                prop = getattr(self, "internalSearch")
                layout.prop_search(
                    self, "internalSearch", bpy.data, "texts", text="")
            elif getattr(self, "codetypeswitch") == 'EXT':
                prop = getattr(self, "shadercode")
                layout.prop(self, "shadercode")
        else:
            # temp until we can create ramps natively
            if self.plugin_name == 'PxrRamp':
                nt = bpy.context.active_object.active_material.node_tree
                if nt:
                    layout.template_color_ramp(
                        nt.nodes[self.color_ramp_dummy_name], 'color_ramp')

            for prop_name in prop_names:
                prop_meta = self.prop_meta[prop_name]
                if 'widget' in prop_meta and prop_meta['widget'] == 'null' or \
                        'hidden' in prop_meta and prop_meta['hidden']:
                    continue
                if prop_name not in self.inputs:
                    if prop_meta['renderman_type'] == 'page':
                        ui_prop = prop_name + "_ui_open"
                        ui_open = getattr(self, ui_prop)
                        icon = 'DISCLOSURE_TRI_DOWN' if ui_open \
                            else 'DISCLOSURE_TRI_RIGHT'

                        split = layout.split(NODE_LAYOUT_SPLIT)
                        row = split.row()
                        row.prop(self, ui_prop, icon=icon, text='',
                                 icon_only=True, emboss=False,slider=True)
                        row.label(prop_name.split('.')[-1] + ':')

                        if ui_open:
                            prop = getattr(self, prop_name)
                            self.draw_nonconnectable_props(
                                context, layout, prop)
                    elif "Subset" in prop_name and prop_meta['type'] == 'string':
                        layout.prop_search(self, prop_name, bpy.data.scenes[0].renderman,
                                           "object_groups")
                    else:
                        layout.prop(self, prop_name,slider=True)

    def copy(self, node):
        pass
    #    self.inputs.clear()
    #    self.outputs.clear()

    def RefreshNodes(self, context, nodeOR=None, materialOverride=None, saveProps=False):

        # Compile shader.        If the call was from socket draw get the node
        # information anther way.
        if hasattr(context, "node"):
            node = context.node
        else:
            node = nodeOR
        prefs = bpy.context.user_preferences.addons[__package__].preferences

        out_path = user_path(prefs.env_vars.out)
        compile_path = os.path.join(user_path(prefs.env_vars.out), "shaders")
        if os.path.exists(out_path):
            pass
        else:
            os.mkdir(out_path)
        if os.path.exists(os.path.join(out_path, "shaders")):
            pass
        else:
            os.mkdir(os.path.join(out_path, "shaders"))
        if getattr(node, "codetypeswitch") == "EXT":
            osl_path = user_path(getattr(node, 'shadercode'))
            FileName = os.path.basename(osl_path)
            FileNameNoEXT = os.path.splitext(FileName)[0]
            FileNameOSO = FileNameNoEXT
            FileNameOSO += ".oso"
            export_path = os.path.join(
                user_path(prefs.env_vars.out), "shaders", FileNameOSO)
            if os.path.splitext(FileName)[1] == ".oso":
                if(not os.path.samefile(osl_path, os.path.join(user_path(prefs.env_vars.out), "shaders", FileNameOSO))):
                    shutil.copy(osl_path, os.path.join(
                        user_path(prefs.env_vars.out), "shaders"))
                # Assume that the user knows what they were doing when they
                # compiled the osl file.
                ok = True
            else:
                ok = node.compile_osl(osl_path, compile_path)
        elif getattr(node, "codetypeswitch") == "INT" and node.internalSearch:
            script = bpy.data.texts[node.internalSearch]
            osl_path = bpy.path.abspath(
                script.filepath, library=script.library)
            if script.is_in_memory or script.is_dirty or \
                    script.is_modified or not os.path.exists(osl_path):
                osl_file = tempfile.NamedTemporaryFile(
                    mode='w', suffix=".osl", delete=False)
                osl_file.write(script.as_string())
                osl_file.close()
                FileNameNoEXT = os.path.splitext(script.name)[0]
                FileNameOSO = FileNameNoEXT
                FileNameOSO += ".oso"
                ok = node.compile_osl(osl_file.name, compile_path, script.name)
                export_path = os.path.join(
                    user_path(prefs.env_vars.out), "shaders", FileNameOSO)
                os.remove(osl_file.name)
            else:
                ok = node.compile_osl(osl_path, compile_path)
                FileName = os.path.basename(osl_path)
                FileNameNoEXT = os.path.splitext(FileName)[0]
                FileNameOSO = FileNameNoEXT
                FileNameOSO += ".oso"
                export_path = os.path.join(
                    user_path(prefs.env_vars.out), "shaders", FileNameOSO)
        else:
            ok = False
            debug("osl", "Shader cannot be compiled. Shader name not specified")
        # If Shader compiled successfully then update node.
        if ok:
            debug('osl', "Shader Compiled Successfully!")
            # Reset the inputs and outputs
            if(not saveProps):
                node.outputs.clear()
                node.inputs.clear()
            # Read in new properties
            prop_names, shader_meta = readOSO(export_path)
            debug('osl', prop_names, "MetaInfo: ", shader_meta)
            # Set node name to shader name
            node.label = shader_meta["shader"]
            # Generate new inputs and outputs
            node.OSLPROPSPOINTER = OSLProps
            node.OSLPROPSPOINTER.setProps(
                node, prop_names, shader_meta, context, materialOverride, saveProps)
            setattr(node, 'shader_meta', shader_meta)
        else:
            debug("osl", "NODE COMPILATION FAILED")

    def compile_osl(self, inFile, outPath, nameOverride=""):
        if nameOverride == "":
            FileName = os.path.basename(inFile)
            FileNameNoEXT = os.path.splitext(FileName)[0]
            out_file = os.path.join(outPath, FileNameNoEXT)
            out_file += ".oso"
        else:
            FileNameNoEXT = os.path.splitext(nameOverride)[0]
            out_file = os.path.join(outPath, FileNameNoEXT)
            out_file += ".oso"
        ok = _cycles.osl_compile(inFile, out_file)

        return ok

    def update(self):
        debug("info", "UPDATING: ", self.name)

    @classmethod
    def poll(cls, ntree):
        if hasattr(ntree, 'bl_idname'):
            return ntree.bl_idname == 'ShaderNodeTree'
        else:
            return True


class OSLProps(bpy.types.PropertyGroup):
    # Set props takes in self, a list of prop_names, and shader_meta data.
    # Look at the readOSO function (located in util.py) if you need to know
    # the layout.

    def setProps(self, prop_names, shader_meta, context, materialOverride, saveProps):
        if materialOverride is not None:
            mat = materialOverride.name
        else:
            mat = context.object.active_material.name
        setattr(OSLProps, mat + self.name + "shader", shader_meta["shader"])
        setattr(OSLProps, mat + self.name + "prop_namesOSL", prop_names)
        for prop_name in prop_names:
            storageLocation = mat + self.name + prop_name
            if shader_meta[prop_name]["IO"] == "out":
                setattr(OSLProps, storageLocation + "type", "OUT")
                if(not saveProps):
                    self.outputs.new(
                        socket_map[shader_meta[prop_name]["type"]], prop_name)
            else:
                prop_default = shader_meta[prop_name]["default"]
                if shader_meta[prop_name]["type"] == "float":
                    floatResult = float(prop_default)
                    setattr(OSLProps, storageLocation + "type",
                            shader_meta[prop_name]["type"])
                    setattr(OSLProps, storageLocation,
                            FloatProperty(name=prop_name,
                                          default=floatResult,
                                          precision=3))
                elif shader_meta[prop_name]["type"] == "int":
                    debug('osl', "Int property: ", prop_name, prop_default)
                    setattr(OSLProps, storageLocation + "type",
                            shader_meta[prop_name]["type"])
                    setattr(OSLProps, storageLocation,
                            IntProperty(name=prop_name,
                                        default=int(float(prop_default))))
                elif shader_meta[prop_name]["type"] == "color":
                    setattr(OSLProps, storageLocation + "type",
                            shader_meta[prop_name]["type"])
                    setattr(OSLProps, storageLocation,
                            FloatVectorProperty(name=prop_name,
                                                default=prop_default,
                                                subtype='COLOR',
                                                soft_min=0.0,
                                                soft_max=1.0))
                elif shader_meta[prop_name]["type"] == "point":
                    setattr(OSLProps, storageLocation + "type",
                            shader_meta[prop_name]["type"])
                    setattr(OSLProps, storageLocation,
                            FloatVectorProperty(name=prop_name,
                                                default=prop_default,
                                                subtype='XYZ'))
                elif shader_meta[prop_name]["type"] == "vector":
                    setattr(OSLProps, storageLocation + "type",
                            shader_meta[prop_name]["type"])
                    setattr(OSLProps, storageLocation,
                            FloatVectorProperty(name=prop_name,
                                                default=prop_default,
                                                subtype='DIRECTION'))
                elif shader_meta[prop_name]["type"] == "normal":
                    setattr(OSLProps, storageLocation + "type",
                            shader_meta[prop_name]["type"])
                    setattr(OSLProps, storageLocation,
                            FloatVectorProperty(name=prop_name,
                                                default=prop_default,
                                                subtype='XYZ'))
                elif shader_meta[prop_name]["type"] == "matrix":
                    setattr(OSLProps, storageLocation + "type",
                            shader_meta[prop_name]["type"])
                    setattr(OSLProps, storageLocation,
                            FloatVectorProperty(name=prop_name,
                                                default=prop_default,
                                                size=16,))  # subtype = 'MATRIX' This does not work do not use!!!!
                elif shader_meta[prop_name]["type"] == "string":
                    setattr(OSLProps, storageLocation + "type",
                            shader_meta[prop_name]["type"])
                    setattr(OSLProps, storageLocation,
                            StringProperty(name=prop_name,
                                           default=prop_default,
                                           subtype='FILE_PATH'))
                else:
                    setattr(OSLProps, storageLocation + "type",
                            shader_meta[prop_name]["type"])
                    setattr(OSLProps, storageLocation,
                            StringProperty(name=prop_name,
                                           default=prop_default))
                if shader_meta[prop_name]["type"] == "matrix" or \
                        shader_meta[prop_name]["type"] == "point":
                    if(not saveProps):
                        self.inputs.new(socket_map["struct"], prop_name)
                elif shader_meta[prop_name]["type"] == "void":
                    pass
                elif(not saveProps):
                    self.inputs.new(socket_map[shader_meta[prop_name]["type"]],
                                    prop_name)
        debug('osl', "Shader: ", shader_meta["shader"], "Properties: ",
              prop_names, "Shader meta data: ", shader_meta)
        compileLocation = self.name + "Compile"
        setattr(OSLProps, compileLocation, False)

    # for sp in [p for p in args.params if p.meta['array']]:
    # row = layout.row(align=True)
    # row.label(sp.name)
    # row.operator("node.add_array_socket", text='', icon='ZOOMIN').array_name = sp.name
    # row.operator("node.remove_array_socket", text='', icon='ZOOMOUT').array_name = sp.name

    # def draw_buttons_ext(self, context, layout):
    #     row = layout.row(align=True)
    #     row.label("buttons ext")
    #     layout.operator('node.refresh_shader_parameters', icon='FILE_REFRESH')
    # print(self.prop_names)
    # for p in self.prop_names:
    # layout.prop(self, p)
    # for p in self.prop_names:
    # split = layout.split(NODE_LAYOUT_SPLIT)
    # split.label(p+':')
    # split.prop(self, p, text='')


class RendermanOutputNode(RendermanShadingNode):
    bl_label = 'PRMan Material'
    renderman_node_type = 'output'
    bl_icon = 'MATERIAL'
    node_tree = None

    def init(self, context):
        input = self.inputs.new('RendermanShaderSocket', 'Bxdf')
        input.type = 'SHADER'
        input.hide_value = True
        input = self.inputs.new('RendermanShaderSocket', 'Light')
        input.hide_value = True
        input = self.inputs.new('RendermanShaderSocket', 'Displacement')
        input.hide_value = True

    def draw_buttons(self, context, layout):
        return

    def draw_buttons_ext(self, context, layout):
        return

    # when a connection is made or removed see if we're in IPR mode and issue
    # updates
    def update(self):
        from . import engine
        if engine.is_ipr_running():
            engine.ipr.issue_shader_edits(nt=self.id_data)


# Final output node, used as a dummy to find top level shaders
class RendermanBxdfNode(RendermanShadingNode):
    bl_label = 'Bxdf'
    renderman_node_type = 'bxdf'

    shading_compatibility = {'NEW_SHADING'}


class RendermanDisplacementNode(RendermanShadingNode):
    bl_label = 'Displacement'
    renderman_node_type = 'displacement'

# Final output node, used as a dummy to find top level shaders


class RendermanPatternNode(RendermanShadingNode):
    bl_label = 'Texture'
    renderman_node_type = 'pattern'
    bl_type = 'TEX_IMAGE'
    bl_static_type = 'TEX_IMAGE'


class RendermanLightNode(RendermanShadingNode):
    bl_label = 'Output'
    renderman_node_type = 'light'

# Generate dynamic types


def generate_osl_node():
    nodeType = 'pattern'
    name = 'PxrOSL'
    typename = '%s%sNode' % (name, nodeType.capitalize())
    ntype = type(typename, (RendermanPatternNode,), {})
    ntype.bl_label = name
    ntype.typename = typename

    inputs = [ET.fromstring(
        '<param name="shader"  type="string" default=""   widget="default" connectable="False"></param>')]
    outputs = []

    def init(self, context):
        node_add_inputs(self, name, self.prop_names)
        node_add_outputs(self)

    ntype.init = init
    ntype.plugin_name = StringProperty(name='Plugin Name',
                                       default=name, options={'HIDDEN'})
    # lights cant connect to a node tree in 20.0
    class_generate_properties(ntype, name, inputs)
    bpy.utils.register_class(ntype)
    bpy.types.ShaderNodeTree.nodetypes[typename] = ntype


def generate_node_type(prefs, name, args):
    ''' Dynamically generate a node type from pattern '''

    nodeType = args.find("shaderType/tag").attrib['value']
    typename = '%s%sNode' % (name, nodeType.capitalize())
    nodeDict = {'bxdf': RendermanBxdfNode,
                'pattern': RendermanPatternNode,
                'displacement': RendermanDisplacementNode,
                'light': RendermanLightNode}
    if nodeType not in nodeDict.keys():
        return
    ntype = type(typename, (nodeDict[nodeType],), {})
    ntype.bl_label = name
    ntype.typename = typename

    inputs = [p for p in args.findall('./param')] + \
        [p for p in args.findall('./page')]
    outputs = [p for p in args.findall('.//output')]

    def init(self, context):
        if self.renderman_node_type == 'bxdf':
            self.outputs.new('RendermanShaderSocket', "Bxdf").type = 'SHADER'
            #socket_template = self.socket_templates.new(identifier='Bxdf', name='Bxdf', type='SHADER')
            node_add_inputs(self, name, self.prop_names)
            node_add_outputs(self)
        elif self.renderman_node_type == 'light':
            # only make a few sockets connectable
            node_add_inputs(self, name, self.prop_names)
            self.outputs.new('RendermanShaderSocket', "Light")
        elif self.renderman_node_type == 'displacement':
            # only make the color connectable
            self.outputs.new('RendermanShaderSocket', "Displacement")
            node_add_inputs(self, name, self.prop_names)
        # else pattern
        elif name == "PxrOSL":
            self.outputs.clear()
        else:
            node_add_inputs(self, name, self.prop_names)
            node_add_outputs(self)

        if name == "PxrRamp":
            active_mat = bpy.context.active_object.active_material
            if not active_mat.use_nodes:
                active_mat.use_nodes = True
            color_ramp = active_mat.node_tree.nodes.new('ShaderNodeValToRGB')
            self.color_ramp_dummy_name = color_ramp.name

    ntype.init = init
    if name == 'PxrRamp':
        ntype.color_ramp_dummy_name = StringProperty('color_ramp', default='')

    ntype.plugin_name = StringProperty(name='Plugin Name',
                                       default=name, options={'HIDDEN'})
    # lights cant connect to a node tree in 20.0
    class_generate_properties(ntype, name, inputs + outputs)
    if nodeType == 'light':
        ntype.light_shading_rate = FloatProperty(
            name="Light Shading Rate",
            description="Shading Rate for this light.  \
                Leave this high unless detail is missing",
            default=100.0)
        ntype.light_primary_visibility = BoolProperty(
            name="Light Primary Visibility",
            description="Camera visibility for this light",
            default=True)

    bpy.utils.register_class(ntype)

    return typename, ntype


# UI
def find_node_input(node, name):
    for input in node.inputs:
        if input.name == name:
            return input

    return None


def find_node(material, nodetype):
    if material and material.node_tree:
        ntree = material.node_tree

        active_output_node = None
        for node in ntree.nodes:
            if getattr(node, "bl_idname", None) == nodetype:
                if getattr(node, "is_active_output", True):
                    return node
                if not active_output_node:
                    active_output_node = node
        return active_output_node

    return None


def find_node_input(node, name):
    for input in node.inputs:
        if input.name == name:
            return input

    return None


def panel_node_draw(layout, context, id_data, output_type, input_name):
    ntree = id_data.node_tree

    node = find_node(id_data, output_type)
    if not node:
        layout.label(text="No output node")
    else:
        input = find_node_input(node, input_name)
        #layout.template_node_view(ntree, node, input)
        draw_nodes_properties_ui(layout, context, ntree)

    return True


def is_renderman_nodetree(material):
    return find_node(material, 'RendermanOutputNode')


def draw_nodes_properties_ui(layout, context, nt, input_name='Bxdf',
                             output_node_type="output"):
    output_node = next((n for n in nt.nodes
                        if hasattr(n, 'renderman_node_type') and n.renderman_node_type == output_node_type), None)
    if output_node is None:
        return

    socket = output_node.inputs[input_name]
    node = socket_node_input(nt, socket)

    layout.context_pointer_set("nodetree", nt)
    layout.context_pointer_set("node", output_node)
    layout.context_pointer_set("socket", socket)

    split = layout.split(0.35)
    split.label(socket.name + ':')

    if socket.is_linked:
        # for lights draw the shading rate ui.

        split.operator_menu_enum("node.add_%s" % input_name.lower(),
                                 "node_type", text=node.bl_label)
    else:
        split.operator_menu_enum("node.add_%s" % input_name.lower(),
                                 "node_type", text='None')

    if node is not None:
        draw_node_properties_recursive(layout, context, nt, node)


def node_shader_handle(nt, node):
    return '%s_%s' % (nt.name, node.name)


def socket_node_input(nt, socket):
    return next((l.from_node for l in nt.links if l.to_socket == socket), None)


def socket_socket_input(nt, socket):
    return next((l.from_socket for l in nt.links if l.to_socket == socket and socket.is_linked),
                None)


def linked_sockets(sockets):
    if sockets is None:
        return []
    return [i for i in sockets if i.is_linked]


def draw_node_properties_recursive(layout, context, nt, node, level=0):

    def indented_label(layout, label, level):
        for i in range(level):
            layout.label('', icon='BLANK1')
        if label:
            layout.label(label)

    layout.context_pointer_set("node", node)
    layout.context_pointer_set("nodetree", nt)

    def draw_props(prop_names, layout, level):
        if node.plugin_name == "PxrOSL":
            pass
        else:
            for prop_name in prop_names:
                # skip showing the shape for PxrStdAreaLight
                if prop_name in ["lightGroup", "rman__Shape", "coneAngle", "penumbraAngle"]:
                    continue

                if prop_name == "codetypeswitch":
                    row = layout.row()
                    if node.codetypeswitch == 'INT':
                        row.prop_search(node, "internalSearch",
                                        bpy.data, "texts", text="")
                    elif node.codetypeswitch == 'EXT':
                        row.prop(node, "shadercode")
                elif prop_name == "internalSearch" or prop_name == "shadercode" or prop_name == "expression":
                    pass
                else:
                    prop_meta = node.prop_meta[prop_name]
                    prop = getattr(node, prop_name)

                    if 'widget' in prop_meta and prop_meta['widget'] == 'null' or \
                        'hidden' in prop_meta and prop_meta['hidden']:
                        continue

                    # else check if the socket with this name is connected
                    socket = node.inputs[prop_name] if prop_name in node.inputs \
                        else None
                    layout.context_pointer_set("socket", socket)

                    if socket and socket.is_linked:
                        input_node = socket_node_input(nt, socket)
                        icon = 'DISCLOSURE_TRI_DOWN' if socket.ui_open \
                            else 'DISCLOSURE_TRI_RIGHT'

                        split = layout.split(NODE_LAYOUT_SPLIT)
                        row = split.row()
                        indented_label(row, None, level)
                        row.prop(socket, "ui_open", icon=icon, text='',
                                 icon_only=True, emboss=False)
                        label = prop_meta.get('label', prop_name)
                        row.label(label + ':')
                        if prop_meta['renderman_type'] == 'vstruct' or prop_name == 'inputMaterial':
                            split.operator_menu_enum("node.add_layer", "node_type",
                                                 text=input_node.bl_label, icon="LAYER_USED")
                        elif prop_meta['renderman_type'] == 'struct':
                            split.operator_menu_enum("node.add_manifold", "node_type",
                                                 text=input_node.bl_label, icon="LAYER_USED")
                        elif prop_meta['renderman_type'] == 'normal':
                            split.operator_menu_enum("node.add_bump", "node_type",
                                                 text=input_node.bl_label, icon="LAYER_USED")
                        else:
                            split.operator_menu_enum("node.add_pattern", "node_type",
                                                 text=input_node.bl_label, icon="LAYER_USED")

                        if socket.ui_open:
                            draw_node_properties_recursive(layout, context, nt,
                                                           input_node, level=level + 1)

                    else:
                        row = layout.row(align=True)
                        if prop_meta['renderman_type'] == 'page':
                            ui_prop = prop_name + "_ui_open"
                            ui_open = getattr(node, ui_prop)
                            icon = 'DISCLOSURE_TRI_DOWN' if ui_open \
                                else 'DISCLOSURE_TRI_RIGHT'

                            split = layout.split(NODE_LAYOUT_SPLIT)
                            row = split.row()
                            for i in range(level):
                                row.label('', icon='BLANK1')
                            row.prop(node, ui_prop, icon=icon, text='',
                                     icon_only=True, emboss=False)
                            row.label(prop_name.split('.')[-1] + ':')

                            if ui_open:
                                draw_props(prop, layout, level + 1)

                        else:
                            indented_label(row, None, level)
                            # indented_label(row, socket.name+':')
                            # don't draw prop for struct type
                            if "Subset" in prop_name and prop_meta['type'] == 'string':
                                row.prop_search(node, prop_name, bpy.data.scenes[0].renderman,
                                                "object_groups")
                            else:
                                if prop_meta['renderman_type'] != 'struct':
                                    row.prop(node, prop_name,slider=True)
                                else:
                                    row.label(prop_meta['label'])
                            if prop_name in node.inputs:
                                if prop_meta['renderman_type'] == 'vstruct' or prop_name == 'inputMaterial':
                                    row.operator_menu_enum("node.add_layer", "node_type",
                                                         text='', icon="LAYER_USED")
                                elif prop_meta['renderman_type'] == 'struct':
                                    row.operator_menu_enum("node.add_manifold", "node_type",
                                                         text='', icon="LAYER_USED")
                                elif prop_meta['renderman_type'] == 'normal':
                                    row.operator_menu_enum("node.add_bump", "node_type",
                                                         text='', icon="LAYER_USED")
                                else:
                                    row.operator_menu_enum("node.add_pattern", "node_type",
                                                         text='', icon="LAYER_USED")

    # if this is a cycles node do something different
    if not hasattr(node, 'plugin_name'):
        node.draw_buttons(context, layout)
        for input in node.inputs:
            if input.is_linked:
                input_node = socket_node_input(nt, input)
                icon = 'DISCLOSURE_TRI_DOWN' if input.show_expanded \
                    else 'DISCLOSURE_TRI_RIGHT'

                split = layout.split(NODE_LAYOUT_SPLIT)
                row = split.row()
                indented_label(row, None, level)
                row.prop(input, "show_expanded", icon=icon, text='',
                         icon_only=True, emboss=False)
                row.label(input.name + ':')
                split.operator_menu_enum("node.add_pattern", "node_type",
                                         text=input_node.bl_label, icon="LAYER_USED")

                if input.show_expanded:
                    draw_node_properties_recursive(layout, context, nt,
                                                   input_node, level=level + 1)

            else:
                row = layout.row(align=True)
                indented_label(row, None, level)
                # indented_label(row, socket.name+':')
                # don't draw prop for struct type
                if input.hide_value:
                    row.label(input.name)
                else:
                    row.prop(input, 'default_value', slider=True)
                row.operator_menu_enum("node.add_pattern", "node_type",
                                           text='', icon="LAYER_USED")
    else:
        if node.plugin_name == 'PxrRamp':
            dummy_nt = bpy.context.active_object.active_material.node_tree
            if dummy_nt:
                layout.template_color_ramp(
                    dummy_nt.nodes[node.color_ramp_dummy_name], 'color_ramp')
        draw_props(node.prop_names, layout, level)
    layout.separator()


# Operators
# connect the pattern nodes in some sensible manner (color output to color input etc)
# TODO more robust
def link_node(nt, from_node, in_socket):
    out_socket = None
    # first look for resultF/resultRGB
    if type(in_socket).__name__ in ['RendermanNodeSocketColor',
                                    'RendermanNodeSocketVector']:
        out_socket = from_node.outputs.get('resultRGB',
                                           next((s for s in from_node.outputs
                                                 if type(s).__name__ == 'RendermanNodeSocketColor'), None))
    elif type(in_socket).__name__ == 'RendermanNodeSocketStruct':
        out_socket = from_node.outputs.get('result', None)
    else:
        out_socket = from_node.outputs.get('resultF',
                                           next((s for s in from_node.outputs
                                                 if type(s).__name__ == 'RendermanNodeSocketFloat'), None))

    if out_socket:
        nt.links.new(out_socket, in_socket)

# bass class for operator to add a node


class Add_Node:

    '''
    For generating cycles-style ui menus to add new nodes,
    connected to a given input socket.
    '''

    def get_type_items(self, context):
        items = []
        # if this is a pattern input do columns!
        if self.input_type.lower() == 'pattern':
            i = 0
            for pattern_cat, patterns in pattern_categories.items():
                if pattern_cat.lower() in ['layer','script','manifold','bump','displace']:
                    continue
                items.append(('', pattern_cat, pattern_cat, '', 0))
                for nodename in sorted(patterns):
                    nodetype = patterns[nodename]
                    items.append((nodetype.typename, nodetype.bl_label,
                                  nodetype.bl_label, '', i))
                    i += 1
                items.append(('', '', '', '', 0))
            items.append(('REMOVE', 'Remove',
                  'Remove the node connected to this socket', '', i+1))
            items.append(('DISCONNECT', 'Disconnect',
                  'Disconnect the node connected to this socket', '', i+2))
                
        elif self.input_type.lower() in ['layer', 'manifold', 'bump']:
            patterns = pattern_categories[self.input_type]
            for nodename in sorted(patterns):
                nodetype = patterns[nodename]
                items.append((nodetype.typename, nodetype.bl_label,
                              nodetype.bl_label))
                
            items.append(('REMOVE', 'Remove',
                  'Remove the node connected to this socket'))
            items.append(('DISCONNECT', 'Disconnect',
                  'Disconnect the node connected to this socket'))
        else:
            for nodetype in nodetypes.values():
                if self.input_type.lower() == 'light' and nodetype.renderman_node_type == 'light':
                    if nodetype.__name__ == 'PxrMeshLightLightNode':
                        items.append((nodetype.typename, nodetype.bl_label,
                                      nodetype.bl_label))
                elif nodetype.renderman_node_type == self.input_type.lower():
                    items.append((nodetype.typename, nodetype.bl_label,
                                  nodetype.bl_label))
            items = sorted(items, key=itemgetter(1))
            items.append(('REMOVE', 'Remove',
                          'Remove the node connected to this socket'))
            items.append(('DISCONNECT', 'Disconnect',
                          'Disconnect the node connected to this socket'))
        return items

    node_type = EnumProperty(name="Node Type",
                             description='Node type to add to this socket',
                             items=get_type_items)

    def execute(self, context):
        new_type = self.properties.node_type
        if new_type == 'DEFAULT':
            return {'CANCELLED'}

        nt = context.nodetree
        node = context.node
        socket = context.socket
        input_node = socket_node_input(nt, socket)

        if new_type == 'REMOVE':
            nt.nodes.remove(input_node)
            return {'FINISHED'}

        if new_type == 'DISCONNECT':
            link = next((l for l in nt.links if l.to_socket == socket), None)
            nt.links.remove(link)
            return {'FINISHED'}

        # add a new node to existing socket
        if input_node is None:
            newnode = nt.nodes.new(new_type)
            newnode.location = node.location
            newnode.location[0] -= 300
            newnode.selected = False
            if self.input_type == 'Pattern':
                link_node(nt, newnode, socket)
            else:
                nt.links.new(newnode.outputs[self.input_type], socket)

        # replace input node with a new one
        else:
            newnode = nt.nodes.new(new_type)
            input = socket
            old_node = input.links[0].from_node
            if self.input_type == 'Pattern':
                link_node(nt, newnode, socket)
            else:
                nt.links.new(newnode.outputs[self.input_type], socket)
            newnode.location = old_node.location
            active_material = context.active_object.active_material
            newnode.update_mat(active_material)
            nt.nodes.remove(old_node)
        return {'FINISHED'}


class NODE_OT_add_bxdf(bpy.types.Operator, Add_Node):

    '''
    For generating cycles-style ui menus to add new bxdfs,
    connected to a given input socket.
    '''

    bl_idname = 'node.add_bxdf'
    bl_label = 'Add Bxdf Node'
    bl_description = 'Connect a Bxdf to this socket'
    input_type = StringProperty(default='Bxdf')


class NODE_OT_add_displacement(bpy.types.Operator, Add_Node):

    '''
    For generating cycles-style ui menus to add new nodes,
    connected to a given input socket.
    '''

    bl_idname = 'node.add_displacement'
    bl_label = 'Add Displacement Node'
    bl_description = 'Connect a Displacement shader to this socket'
    input_type = StringProperty(default='Displacement')


class NODE_OT_add_light(bpy.types.Operator, Add_Node):

    '''
    For generating cycles-style ui menus to add new nodes,
    connected to a given input socket.
    '''

    bl_idname = 'node.add_light'
    bl_label = 'Add Light Node'
    bl_description = 'Connect a Light shader to this socket'
    input_type = StringProperty(default='Light')


class NODE_OT_add_pattern(bpy.types.Operator, Add_Node):

    '''
    For generating cycles-style ui menus to add new nodes,
    connected to a given input socket.
    '''

    bl_idname = 'node.add_pattern'
    bl_label = 'Add Pattern Node'
    bl_description = 'Connect a Pattern to this socket'
    input_type = StringProperty(default='Pattern')

class NODE_OT_add_layer(bpy.types.Operator, Add_Node):
    '''
    For generating cycles-style ui menus to add new nodes,
    connected to a given input socket.
    '''

    bl_idname = 'node.add_layer'
    bl_label = 'Add Layer Node'
    bl_description = 'Connect a PxrLayer'
    input_type = StringProperty(default='Layer')

class NODE_OT_add_manifold(bpy.types.Operator, Add_Node):
    '''
    For generating cycles-style ui menus to add new nodes,
    connected to a given input socket.
    '''

    bl_idname = 'node.add_manifold'
    bl_label = 'Add Manifold Node'
    bl_description = 'Connect a Manifold'
    input_type = StringProperty(default='Manifold')

class NODE_OT_add_bump(bpy.types.Operator, Add_Node):
    '''
    For generating cycles-style ui menus to add new nodes,
    connected to a given input socket.
    '''

    bl_idname = 'node.add_bump'
    bl_label = 'Add Bump Node'
    bl_description = 'Connect a bump node'
    input_type = StringProperty(default='Bump')

# return if this param has a vstuct connection or linked independently


def is_vstruct_or_linked(node, param):
    meta = node.prop_meta[param]

    if 'vstructmember' not in meta.keys():
        return node.inputs[param].is_linked
    elif param in node.inputs and node.inputs[param].is_linked:
        return True
    else:
        vstruct_name, vstruct_member = meta['vstructmember'].split('.')
        if node.inputs[vstruct_name].is_linked:
            from_socket = node.inputs[vstruct_name].links[0].from_socket
            vstruct_from_param = "%s_%s" % (
                from_socket.identifier, vstruct_member)
            return vstruct_conditional(from_socket.node, vstruct_from_param)
        else:
            return False

# tells if this param has a vstuct connection that is linked and
# conditional met


def is_vstruct_and_linked(node, param):
    meta = node.prop_meta[param]

    if 'vstructmember' not in meta.keys():
        return False
    else:
        vstruct_name, vstruct_member = meta['vstructmember'].split('.')
        if node.inputs[vstruct_name].is_linked:
            from_socket = node.inputs[vstruct_name].links[0].from_socket
            vstruct_from_param = "%s_%s" % (
                from_socket.identifier, vstruct_member)
            return vstruct_conditional(from_socket.node, vstruct_from_param)
        else:
            return False

# gets the value for a node walking up the vstruct chain


def get_val_vstruct(node, param):
    if param in node.inputs and node.inputs[param].is_linked:
        from_socket = node.inputs[param].links[0].from_socket
        return get_val_vstruct(from_socket.node, from_socket.identifier)
    elif is_vstruct_and_linked(node, param):
        return True
        #meta = node.shader_meta[param] if node.bl_idname == "PxrOSLPatternNode" else node.prop_meta[param]
        #vstruct_name, vstruct_member = meta['vstructmember'].split('.')
        #from_socket = node.inputs[vstruct_name].links[0].from_socket
        #vstruct_from_param = "%s_%s" % (from_socket.identifier, vstruct_member)
        #print('vstruct linked  %s %s' % (node.name, param))
        # return get_val_vstruct(from_socket.node, vstruct_from_param)
    else:
        return getattr(node, param)

# parse a vstruct conditional string and return true or false if should link


def vstruct_conditional(node, param):

    meta = getattr(
        node, 'shader_meta') if node.bl_idname == "PxrOSLPatternNode" else node.output_meta
    if param not in meta:
        return False
    meta = meta[param]
    if 'vstructConditionalExpr' not in meta.keys():
        return True

    expr = meta['vstructConditionalExpr']
    expr = expr.replace('connect if ', '')
    set_zero = False
    if ' else set 0' in expr:
        expr = expr.replace(' else set 0', '')
        set_zero = True

    tokens = expr.split()
    new_tokens = []
    i = 0
    num_tokens = len(tokens)
    while i < num_tokens:
        token = tokens[i]
        prepend, append = '', ''
        while token[0] == '(':
            token = token[1:]
            prepend += '('
        while token[-1] == ')':
            token = token[:-1]
            append += ')'

        if token == 'set':
            i += 1
            continue

        # is connected change this to node.inputs.is_linked
        if i < num_tokens - 2 and tokens[i + 1] == 'is'\
                and 'connected' in tokens[i + 2]:
            token = "is_vstruct_or_linked(node, '%s')" % token
            last_token = tokens[i + 2]
            while last_token[-1] == ')':
                last_token = last_token[:-1]
                append += ')'
            i += 3
        else:
            i += 1
        if hasattr(node, token):
            token = "get_val_vstruct(node, '%s')" % token

        new_tokens.append(prepend + token + append)

    if 'if' in new_tokens and 'else' not in new_tokens:
        new_tokens.extend(['else', 'False'])
    return eval(" ".join(new_tokens))

# Rib export

# generate param list


def gen_params(ri, node, mat_name=None):
    params = {}
    # If node is OSL node get properties from dynamic location.
    if node.bl_idname == "PxrOSLPatternNode" and mat_name != 'preview':
        getLocation = bpy.context.scene.OSLProps
        prop_namesOSL = getattr(
            getLocation, mat_name + node.name + "prop_namesOSL")
        # params['%s' % ("shader")] = getattr(
        #    getLocation, mat_name + node.name + "shader")
        for prop_name in prop_namesOSL:
            if prop_name == "shadercode" or prop_name == "codetypeswitch" \
                    or prop_name == "internalSearch":
                pass
            else:
                osl_prop_name = mat_name + node.name + prop_name
                prop_type = getattr(getLocation, "%stype" % osl_prop_name)
                if prop_type == "OUT":
                    pass
                elif prop_name in node.inputs and \
                        node.inputs[prop_name].is_linked:
                    from_socket = node.inputs[prop_name].links[0].from_socket
                    params['reference %s %s' % (prop_type, prop_name)] = \
                        [get_output_param_str(
                            from_socket.node, mat_name, from_socket)]
                else:
                    if prop_type == "string" and getattr(getLocation,
                                                         osl_prop_name) != "":
                        textureParam = getattr(getLocation, osl_prop_name)
                        textureName = os.path.splitext(
                            os.path.basename(textureParam))[0]
                        textureName += ".tex"
                        params['%s %s' % (prop_type, prop_name)] = \
                            rib(textureName, type_hint=prop_type)
                    else:
                        params['%s %s' % (prop_type, prop_name)] = \
                            rib(getattr(getLocation, osl_prop_name),
                                type_hint=prop_type)

    # Special case for SeExpr Nodes. Assume that the code will be in a file so
    # that needs to be extracted.
    elif node.bl_idname == "PxrSeExprPatternNode":
        fileInputType = node.codetypeswitch

        for prop_name, meta in node.prop_meta.items():
            if prop_name in txmake_options.index or prop_name == "codetypeswitch":
                pass
            elif prop_name == "internalSearch" and fileInputType == 'INT':
                if node.internalSearch != "":
                    script = bpy.data.texts[node.internalSearch]
                    params['%s %s' % ("string",
                                      "expression")] = \
                        rib(script.as_string(),
                            type_hint=meta['renderman_type'])
            elif prop_name == "shadercode" and fileInputType == "EXT":
                fileInput = user_path(getattr(node, 'shadercode'))
                if fileInput != "":
                    outputString = ""
                    with open(fileInput, encoding='utf-8') as SeExprFile:
                        for line in SeExprFile:
                            outputString += line
                    params['%s %s' % ("string",
                                      "expression")] = \
                        rib(outputString, type_hint=meta['renderman_type'])
            else:
                prop = getattr(node, prop_name)
                # if property group recurse
                if meta['renderman_type'] == 'page':
                    continue
                # if input socket is linked reference that
                elif prop_name in node.inputs and \
                        node.inputs[prop_name].is_linked:
                    from_socket = node.inputs[prop_name].links[0].from_socket
                    params['reference %s %s' % (meta['renderman_type'],
                                                meta['renderman_name'])] = \
                        [get_output_param_str(
                            from_socket.node, mat_name, from_socket)]
                # else output rib
                else:
                    # if struct is not linked continue
                    if meta['renderman_type'] == 'struct':
                        continue

                    if 'options' in meta and meta['options'] == 'texture' or \
                        (node.renderman_node_type == 'light' and
                            'widget' in meta and meta['widget'] == 'fileInput'):

                        params['%s %s' % (meta['renderman_type'],
                                          meta['renderman_name'])] = \
                            rib(get_tex_file_name(prop),
                                type_hint=meta['renderman_type'])
                    elif 'arraySize' in meta:
                        params['%s[%d] %s' % (meta['renderman_type'], len(prop),
                                              meta['renderman_name'])] \
                            = rib(prop)
                    else:
                        params['%s %s' % (meta['renderman_type'],
                                          meta['renderman_name'])] = \
                            rib(prop, type_hint=meta['renderman_type'])
    else:
        for prop_name, meta in node.prop_meta.items():
            if prop_name in txmake_options.index:
                pass
            elif node.plugin_name == 'PxrRamp' and prop_name in ['colors', 'positions']:
                pass

            elif(prop_name in ['sblur', 'tblur', 'notes']):
                pass

            else:
                prop = getattr(node, prop_name)
                # if property group recurse
                if meta['renderman_type'] == 'page':
                    continue
                elif prop_name == 'inputMaterial' or \
                    ('type' in meta and meta['type'] == 'vstruct'):
                    continue

                # if input socket is linked reference that
                elif hasattr(node, 'inputs') and prop_name in node.inputs and \
                        node.inputs[prop_name].is_linked:
                    from_socket = node.inputs[prop_name].links[0].from_socket
                    from_node = node.inputs[prop_name].links[0].from_node
                    params['reference %s %s' % (meta['renderman_type'],
                                                meta['renderman_name'])] = \
                        [get_output_param_str(
                            from_node, mat_name, from_socket)]
                
                # see if vstruct linked
                elif is_vstruct_and_linked(node, prop_name):
                    vstruct_name, vstruct_member = meta[
                        'vstructmember'].split('.')
                    from_socket = node.inputs[
                        vstruct_name].links[0].from_socket
                    vstruct_from_param = "%s_%s" % (
                        from_socket.identifier, vstruct_member)
                    if vstruct_from_param in from_socket.node.output_meta:
                        actual_socket = from_socket.node.output_meta[
                            vstruct_from_param]
                        params['reference %s %s' % (meta['renderman_type'],
                                                    meta['renderman_name'])] = \
                            [get_output_param_str(
                                from_socket.node, mat_name, actual_socket)]
                    else:
                        print('Warning! %s not found on %s' %
                              (vstruct_from_param, from_socket.node.name))

                
                # else output rib
                else:
                    # if struct is not linked continue
                    if meta['renderman_type'] in ['struct', 'enum']:
                        continue

                    if 'options' in meta and meta['options'] == 'texture' \
                        and node.bl_idname != "PxrPtexturePatternNode" or \
                        ('widget' in meta and meta['widget'] == 'assetIdInput'):
                        params['%s %s' % (meta['renderman_type'],
                                          meta['renderman_name'])] = \
                            rib(get_tex_file_name(prop),
                                type_hint=meta['renderman_type'])
                    elif 'arraySize' in meta:
                        if type(prop) == int:
                            prop = [prop]
                        params['%s[%d] %s' % (meta['renderman_type'], len(prop),
                                              meta['renderman_name'])] \
                            = rib(prop)
                    else:
                        params['%s %s' % (meta['renderman_type'],
                                          meta['renderman_name'])] = \
                            rib(prop, type_hint=meta['renderman_type'])
    if node.plugin_name == 'PxrRamp':
        if mat_name not in bpy.data.materials:
            return params
        nt = bpy.data.materials[mat_name].node_tree
        if nt:
            dummy_ramp = nt.nodes[node.color_ramp_dummy_name]
            colors = []
            positions = []
            # double the start and end points
            positions.append(float(dummy_ramp.color_ramp.elements[0].position))
            colors.extend(dummy_ramp.color_ramp.elements[0].color[:3])
            for e in dummy_ramp.color_ramp.elements:
                positions.append(float(e.position))
                colors.extend(e.color[:3])
            positions.append(
                float(dummy_ramp.color_ramp.elements[-1].position))
            colors.extend(dummy_ramp.color_ramp.elements[-1].color[:3])
            params['color[%d] colors' % len(positions)] = colors
            params['float[%d] positions' % len(positions)] = positions
            debug('error', "Params gen: ", params)

    return params


def create_rman_surface(nt, parent_node, input_index, node_type="PxrSurfaceBxdfNode"):
    layer = nt.nodes.new(node_type)
    nt.links.new(layer.outputs[0], parent_node.inputs[input_index])
    setattr(layer, 'enableDiffuse', False)
    
    layer.location = parent_node.location
    layer.diffuseGain = 0
    layer.location[0] -= 300
    return layer

combine_nodes = ['ShaderNodeAddShader', 'ShaderNodeMixShader']

# rman_parent could be PxrSurface or PxrMixer
def convert_cycles_bsdf(nt, rman_parent, node, input_index):

    # if mix or add pass both to parent
    if node.bl_idname in combine_nodes:
        i = 0 if node.bl_idname == 'ShaderNodeAddShader' else 1
        
        node1 = node.inputs[0 + i].links[0].from_node if node.inputs[0 + i].is_linked else None
        node2 = node.inputs[1 + i].links[0].from_node if node.inputs[1 + i].is_linked else None
        
        if not node1 and not node2:
            return
        elif not node1:
            convert_cycles_bsdf(nt, rman_parent, node2, input_index)
        elif not node2:
            convert_cycles_bsdf(nt, rman_parent, node1, input_index)
            
        # if ones a combiner or they're of the same type and not glossy we need
        # to make a mixer
        elif node.bl_idname == 'ShaderNodeMixShader' or node1.bl_idname in combine_nodes \
            or node2.bl_idname in combine_nodes or \
            (bsdf_map[node1.bl_idname][0] == bsdf_map[node2.bl_idname][0]):
            mixer = nt.nodes.new('PxrLayerMixerPatternNode')
            # if parent is output make a pxr surface first
            nt.links.new(mixer.outputs["pxrMaterialOut"],
                         rman_parent.inputs[input_index])
            offset_node_location(rman_parent, mixer, node)

            # set the layer masks
            if node.bl_idname == 'ShaderNodeAddShader':
                mixer.layer1Mask = .5
            else:
                convert_cycles_input(nt, node.inputs['Fac'], mixer, 'layer1Mask')

            # make a new node for each
            convert_cycles_bsdf(nt, mixer, node1, 0)
            convert_cycles_bsdf(nt, mixer, node2, 1)

        # this is a heterogenous mix of add
        else:
            convert_cycles_bsdf(nt, rman_parent, node1, 0)
            convert_cycles_bsdf(nt, rman_parent, node2, 1)

    # else set lobe on parent
    elif 'Bsdf' in node.bl_idname or node.bl_idname == 'ShaderNodeSubsurfaceScattering':
        if rman_parent.plugin_name == 'PxrLayerMixer':
            old_parent = rman_parent
            rman_parent = create_rman_surface(nt, rman_parent, input_index, 
                                              'PxrLayerPatternNode')
            offset_node_location(old_parent, rman_parent, node)

        node_type = node.bl_idname
        bsdf_map[node_type][1](nt, node, rman_parent)
    # if we find an emission node, naively make it a meshlight
    # note this will only make the last emission node the light
    elif node.bl_idname == 'ShaderNodeEmission':
        output = next((n for n in nt.nodes if hasattr(n, 'renderman_node_type') and
                        n.renderman_node_type == 'output'),
                       None)
        meshlight = nt.nodes.new("PxrMeshLightLightNode")
        nt.links.new(meshlight.outputs[0], output.inputs["Light"])
        meshlight.location = output.location
        meshlight.location[0] -= 300
        setattr(meshlight, 'intensity', node.inputs['Strength'].default_value)
        if node.inputs['Color'].is_linked:
            convert_cycles_input(nt, node.inputs['Color'], meshlight, "textureColor")
        else:
            setattr(meshlight, 'lightColor', node.inputs['Color'].default_value[:3])

    else:
        rman_node = convert_cycles_node(nt, node)
        nt.links.new(rman_node.outputs[0], rman_parent.inputs[input_index])


def convert_cycles_displacement(nt, output_node, displace_socket):
    if displace_socket.is_linked:
        displace = nt.nodes.new("PxrDisplaceDisplacementNode")
        nt.links.new(displace.outputs[0], output_node.inputs['Displacement'])
        displace.location = output_node.location
        offset_node_location(output_node, displace, displace_socket.links[0].from_node)
        
        setattr(displace, 'dispAmount', .01)
        convert_cycles_input(nt, displace_socket, displace, "dispScalar")

    
# could make this more robust to shift the entire nodetree to below the 
# bounds of the cycles nodetree
def set_ouput_node_location(nt, output_node, cycles_output):
    output_node.location = cycles_output.location
    output_node.location[1] -= 500

def offset_node_location(rman_parent, rman_node, cycles_node):
    linked_socket = next((sock for sock in cycles_node.outputs if sock.is_linked),
                       None)
    rman_node.location = rman_parent.location
    if linked_socket:
        rman_node.location += (cycles_node.location - linked_socket.links[0].to_node.location)

    
def convert_cycles_nodetree(id, output_node, reporter):
    # find base node
    from . import cycles_convert
    cycles_convert.converted_nodes = {}
    nt = id.node_tree
    reporter({'INFO'}, 'Converting material ' + id.name + ' to RenderMan')
    cycles_output_node = find_node(id, 'ShaderNodeOutputMaterial')
    if not cycles_output_node:
        reporter({'WARNING'}, 'No Cycles output found ' + id.name)
        return False

    # if no bsdf return false
    if not cycles_output_node.inputs[0].is_linked:
        reporter({'WARNING'}, 'No Cycles bsdf found ' + id.name)
        return False

    #set the output node location
    set_ouput_node_location(nt, output_node, cycles_output_node)

    # walk tree
    cycles_convert.report = reporter
    begin_cycles_node = cycles_output_node.inputs[0].links[0].from_node
    base_surface = create_rman_surface(nt, output_node, 0)
    offset_node_location(output_node, base_surface, begin_cycles_node)
    convert_cycles_bsdf(nt, base_surface, begin_cycles_node, 0)
    convert_cycles_displacement(nt, output_node, cycles_output_node.inputs[2])
    return True

cycles_node_map = {
    'ShaderNodeAttribute': 'node_checker_attribute',
    'ShaderNodeBlackbody': 'node_checker_blackbody',
    'ShaderNodeTexBrick': 'node_brick_texture',
    'ShaderNodeBrightContrast': 'node_brightness',
    'ShaderNodeTexChecker': 'node_checker_texture',
    'ShaderNodeBump': 'node_bump',
    'ShaderNodeCameraData': 'node_camera',
    'ShaderNodeTexChecker': 'node_checker_texture',
    'ShaderNodeCombineHSV': 'node_combine_hsv',
    'ShaderNodeCombineRGB': 'node_combine_rgb',
    'ShaderNodeCombineXYZ': 'node_combine_xyz',
    'ShaderNodeTexEnvironment': 'node_environment_texture',
    'ShaderNodeFresnel': 'node_fresnel',
    'ShaderNodeGamma': 'node_gamma',
    'ShaderNodeGeometry': 'node_geometry',
    'ShaderNodeTexGradient': 'node_gradient_texture',
    'ShaderNodeHairInfo': 'node_hair_info',
    'ShaderNodeInvert': 'node_invert',
    'ShaderNodeHueSaturation': 'node_hsv',
    'ShaderNodeTexImage': 'node_image_texture',
    'ShaderNodeHueSaturation': 'node_hsv',
    'ShaderNodeLayerWeight': 'node_layer_weight',
    'ShaderNodeLightFalloff': 'node_light_falloff',
    'ShaderNodeLightPath': 'node_light_path',
    'ShaderNodeTexMagic': 'node_magic_texture',
    'ShaderNodeMapping': 'node_mapping',
    'ShaderNodeMath': 'node_math',
    'ShaderNodeMixRGB': 'node_mix',
    'ShaderNodeTexMusgrave': 'node_musgrave_texture',
    'ShaderNodeTexNoise': 'node_noise_texture',
    'ShaderNodeNormal': 'node_normal',
    'ShaderNodeNormalMap': 'node_normal_map',
    'ShaderNodeObjectInfo': 'node_object_info',
    'ShaderNodeParticleInfo': 'node_particle_info',
    'ShaderNodeRGBCurve': 'node_rgb_curves',
    'ShaderNodeValToRGB': 'node_rgb_ramp',
    'ShaderNodeSeparateHSV': 'node_separate_hsv',
    'ShaderNodeSeparateRGB': 'node_separate_rgb',
    'ShaderNodeSeparateXYZ': 'node_separate_xyz',
    'ShaderNodeTexSky': 'node_sky_texture',
    'ShaderNodeTangent': 'node_tangent',
    'ShaderNodeTexCoord': 'node_texture_coordinate',
    'ShaderNodeUVMap': 'node_uv_map',
    'ShaderNodeValue': 'node_value',
    'ShaderNodeVectorCurves': 'node_vector_curves',
    'ShaderNodeVectorMath': 'node_vector_math',
    'ShaderNodeVectorTransform': 'node_vector_transform',
    'ShaderNodeTexVoronoi': 'node_voronoi_texture',
    'ShaderNodeTexWave': 'node_wave_texture',
    'ShaderNodeWavelength': 'node_wavelength',
    'ShaderNodeWireframe': 'node_wireframe',
}


def get_node_name(node, mat_name):
    return "%s.%s" % (mat_name, node.name.replace(' ', ''))


def get_socket_name(node, socket):
    if type(socket) == dict:
        return socket['name']
    # if this is a renderman node we can just use the socket name,
    else:
        return socket.identifier


def get_socket_type(node, socket):
    sock_type = socket.type.lower()
    if sock_type == 'rgba':
        return 'color'
    elif sock_type == 'value':
        return 'float'
    elif sock_type == 'vector':
        return 'point'
    else:
        return sock_type


def get_output_param_str(node, mat_name, socket):
    # if this is a node group, hook it up to the input node inside!
    if node.bl_idname == 'ShaderNodeGroup':
        ng = node.node_tree
        group_output = next((n for n in ng.nodes if n.bl_idname == 'NodeGroupOutput'),
                       None)
        if group_output is None:
            return "error:error"

        in_sock = group_output.inputs[socket.name]
        if len(in_sock.links):
            link = in_sock.links[0]
            return "%s:%s" % (get_node_name(link.from_node, mat_name), get_socket_name(link.from_node, link.from_socket))
        else:
            return "error:error"
    if node.bl_idname == 'NodeGroupInput':
        global current_group_node
        
        if current_group_node is None:
            return "error:error"

        in_sock = current_group_node.inputs[socket.name]
        if len(in_sock.links):
            link = in_sock.links[0]
            return "%s:%s" % (get_node_name(link.from_node, mat_name), get_socket_name(link.from_node, link.from_socket))
        else:
            return "error:error"

    return "%s:%s" % (get_node_name(node, mat_name), get_socket_name(node, socket))

# hack!!!
current_group_node = None
def translate_node_group(ri, group_node, mat_name):
    ng = group_node.node_tree
    out = next((n for n in ng.nodes if n.bl_idname == 'NodeGroupOutput'),
                       None)
    if out is None:
        return

    nodes_to_export = gather_nodes(out)
    global current_group_node
    current_group_node = group_node
    for node in nodes_to_export:
        shader_node_rib(ri, node, mat_name=mat_name)
    current_group_node = None
    

def translate_cycles_node(ri, node, mat_name):
    if node.bl_idname == 'ShaderNodeGroup':
        translate_node_group(ri, node, mat_name)
        return

    if node.bl_idname not in cycles_node_map.keys():
        print('No translation for node of type %s named %s' %
              (node.bl_idname, node.name))
        return

    mapping = cycles_node_map[node.bl_idname]
    params = {}
    for in_name, input in node.inputs.items():
        param_name = "%s %s" % (get_socket_type(
            node, input), get_socket_name(node, input))
        if input.is_linked:
            param_name = 'reference ' + param_name
            link = input.links[0]
            param_val = get_output_param_str(
                link.from_node, mat_name, link.from_socket)

        else:
            param_val = rib(input.default_value,
                            type_hint=get_socket_type(node, input))

        params[param_name] = param_val

    #print('doing %s %s' % (node.bl_idname, node.name))
    # print(params)
    ri.Pattern(mapping, get_node_name(node, mat_name), params)


# Export to rib
def shader_node_rib(ri, node, mat_name, disp_bound=0.0, portal=False):
    if not hasattr(node, 'renderman_node_type'):
        return translate_cycles_node(ri, node, mat_name)

    params = gen_params(ri, node, mat_name)
    instance = mat_name + '.' + node.name
    
    params['__instanceid'] = instance

    if node.renderman_node_type == "pattern":
        if node.bl_label == 'PxrOSL':
            getLocation = bpy.context.scene.OSLProps
            shader = getattr(getLocation, mat_name + node.name + "shader")

            ri.Pattern(shader, instance, params)
        else:
            ri.Pattern(node.bl_label, instance, params)
    elif node.renderman_node_type == "light":
        light_group_name = ''
        scene = bpy.context.scene
        for lg in scene.renderman.light_groups:
            if mat_name in lg.members.keys():
                light_group_name = lg.name
                break
        params['string lightGroup'] = light_group_name
        params['__instanceid'] = mat_name

        light_name = node.bl_label
        if portal:
            light_name = 'PxrPortalLight'
            params['string domeColorMap'] = params.pop('string lightColorMap')
        ri.Light(light_name, mat_name, params)
    elif node.renderman_node_type == "lightfilter":
        params['__instanceid'] = mat_name

        light_name = node.bl_label
        ri.LightFilter(light_name, mat_name, params)
    elif node.renderman_node_type == "displacement":
        ri.Attribute('displacementbound', {'sphere': disp_bound})
        ri.Displace(node.bl_label, mat_name, params)
    else:
        ri.Bxdf(node.bl_label, instance, params)


def replace_frame_num(prop):
    frame_num = bpy.data.scenes[0].frame_current
    prop = prop.replace('$f4', str(frame_num).zfill(4))
    prop = prop.replace('$F4', str(frame_num).zfill(4))
    prop = prop.replace('$f3', str(frame_num).zfill(3))
    prop = prop.replace('$f3', str(frame_num).zfill(3))
    return prop

# return the output file name if this texture is to be txmade.


def get_tex_file_name(prop):
    prop = replace_frame_num(prop)
    prop = prop.replace('\\', '\/')
    if prop != '' and prop.rsplit('.', 1) != 'tex':
        return os.path.basename(prop).rsplit('.', 1)[0] + '.tex'
    else:
        return prop


# walk the tree for nodes to export
def gather_nodes(node):
    nodes = []
    for socket in node.inputs:
        if socket.is_linked:
            for sub_node in gather_nodes(socket.links[0].from_node):
                if sub_node not in nodes:
                    nodes.append(sub_node)
    if hasattr(node, 'renderman_node_type') and node.renderman_node_type != 'output':
        nodes.append(node)
    elif not hasattr(node, 'renderman_node_type') and node.bl_idname not in ['ShaderNodeOutputMaterial', 'NodeGroupInput', 'NodeGroupOutput']:
        nodes.append(node)

    return nodes


# for an input node output all "nodes"
def export_shader_nodetree(ri, id, handle=None, disp_bound=0.0, iterate_instance=False):

    if id and id.node_tree:

        if is_renderman_nodetree(id):
            portal = type(
                id).__name__ == 'AreaLamp' and id.renderman.renderman_type == 'PORTAL'
            # if id.renderman.nodetree not in bpy.data.node_groups:
            #    load_tree_from_lib(id)

            nt = id.node_tree
            if not handle:
                handle = id.name

            # if ipr we need to iterate instance num on nodes for edits
            from . import engine
            if engine.ipr and hasattr(id.renderman, 'instance_num'):
                if iterate_instance:
                    id.renderman.instance_num += 1
                else:
                    id.renderman.instance_num = 0
                if id.renderman.instance_num > 0:
                    handle += "_%d" % id.renderman.instance_num

            out = next((n for n in nt.nodes if hasattr(n, 'renderman_node_type') and
                        n.renderman_node_type == 'output'),
                       None)
            if out is None:
                return

            nodes_to_export = gather_nodes(out)
            ri.ArchiveRecord('comment', "Shader Graph")
            for node in nodes_to_export:
                shader_node_rib(ri, node, mat_name=handle,
                                disp_bound=disp_bound, portal=portal)
        elif find_node(id, 'ShaderNodeOutputMaterial'):
            print("Error Material %s needs a RenderMan BXDF" % id.name)


def get_textures_for_node(node, matName=""):
    textures = []
    if hasattr(node, 'bl_idname'):
        if node.bl_idname == "PxrPtexturePatternNode":
            return textures
        if node.bl_idname == "PxrOSLPatternNode":
            context = bpy.context
            OSLProps = context.scene.OSLProps
            LocationString = matName + node.name + "prop_namesOSL"
            for prop_name in getattr(OSLProps, LocationString):
                storageLocation = matName + node.name + prop_name
                if hasattr(OSLProps, storageLocation + "type"):
                    if getattr(OSLProps, storageLocation + "type") == "string":
                        prop = getattr(OSLProps, storageLocation)
                        out_file_name = get_tex_file_name(prop)
                        textures.append((replace_frame_num(prop), out_file_name,
                                         ['-smode', 'periodic', '-tmode',
                                          'periodic']))
                # if input socket is linked reference that
                if prop_name in node.inputs and \
                        node.inputs[prop_name].is_linked:
                    from_socket = node.inputs[prop_name].links[0].from_socket
                    textures = textures + \
                        get_textures_for_node(from_socket.node, matName)
            return textures

    if hasattr(node, 'prop_meta'):
        for prop_name, meta in node.prop_meta.items():
            if prop_name in txmake_options.index:
                pass
            elif hasattr(node, prop_name):
                prop = getattr(node, prop_name)

                if meta['renderman_type'] == 'page':
                    continue

                # if input socket is linked reference that
                elif hasattr(node, 'inputs') and prop_name in node.inputs and \
                        node.inputs[prop_name].is_linked:
                    from_socket = node.inputs[prop_name].links[0].from_socket
                    textures = textures + \
                        get_textures_for_node(from_socket.node, matName)

                # else return a tuple of in name/outname
                else:
                    if ('options' in meta and meta['options'] == 'texture') or \
                        (node.renderman_node_type == 'light' and
                            'widget' in meta and meta['widget'] == 'assetIdInput'):
                        out_file_name = get_tex_file_name(prop)
                        # if they don't match add this to the list
                        if out_file_name != prop:
                            if node.renderman_node_type == 'light' and \
                                    "Dome" in node.bl_label:
                                # no options for now
                                textures.append(
                                    (replace_frame_num(prop), out_file_name, ['-envlatl']))
                            else:
                                # Test and see if options like smode are on
                                # this node.
                                if hasattr(node, "smode"):
                                    optionsList = []
                                    for option in txmake_options.index:
                                        partsOfOption = getattr(
                                            txmake_options, option)
                                        if partsOfOption["exportType"] == "name":
                                            optionsList.append("-" + option)
                                            # Float values need converting
                                            # before they are passed to command
                                            # line
                                            if partsOfOption["type"] == "float":
                                                optionsList.append(
                                                    str(getattr(node, option)))
                                            else:
                                                optionsList.append(
                                                    getattr(node, option))
                                        else:
                                            # Float values need converting
                                            # before they are passed to command
                                            # line
                                            if partsOfOption["type"] == "float":
                                                optionsList.append(
                                                    str(getattr(node, option)))
                                            else:
                                                optionsList.append(
                                                    "-" + getattr(node, option))
                                    textures.append(
                                        (replace_frame_num(prop), out_file_name, optionsList))
                                else:
                                    # no options found add the bare minimum
                                    # options for smooth export.
                                    textures.append((replace_frame_num(prop), out_file_name,
                                                     ['-smode', 'periodic',
                                                      '-tmode', 'periodic']))
    return textures


def get_textures(id):
    textures = []
    if id is None or not id.node_tree:
        return textures

    nt = id.node_tree
    out = find_node(id, 'RendermanOutputNode')
    if out is None:
        return

    for name, inp in out.inputs.items():
        if inp.is_linked:
            textures = textures + \
                get_textures_for_node(inp.links[0].from_node, id.name)

    return textures


pattern_node_categories_map = {"texture": ["PxrFractal", "PxrProjectionLayer", "PxrPtexture", "PxrTexture", "PxrVoronoise", "PxrWorley", "PxrFractalize", "PxrDirt", "PxrLayeredTexture", "PxrMultiTexture"],
                           "bump": ["PxrBump", "PxrNormalMap", "PxrFlakes", "aaOceanPrmanShader", 'PxrAdjustNormal'],
                           "color": ["PxrBlackBody", "PxrBlend", "PxrLayeredBlend", "PxrClamp", "PxrExposure", "PxrGamma", "PxrHSL", "PxrInvert", "PxrMix", "PxrProjectionStack", "PxrRamp", "PxrRemap", "PxrThinFilm", "PxrThreshold", "PxrVary", "PxrChecker", "PxrColorCorrect"],
                           "manifold": ["PxrManifold2D", "PxrManifold3D", "PxrManifold3DN", "PxrProjector", "PxrRoundCube", "PxrBumpManifold2D", "PxrTileManifold"],
                           "geometry": ["PxrDot", "PxrCross", "PxrFacingRatio", "PxrTangentField"],
                           "script": ["PxrOSL", "PxrSeExpr"],
                           "utility": ["PxrAttribute", "PxrGeometricAOVs", "PxrMatteID", "PxrPrimvar", "PxrShadedSide", "PxrTee", "PxrToFloat", "PxrToFloat3", "PxrVariable"],
                           "displace": ["PxrDispScalarLayer", 'PxrDispTransform', 'PxrDispVectorLayer'],
                           "layer": ['PxrLayer', 'PxrLayerMixer']}
# Node Chatagorization List
def GetPatternCategory(name): 
    for cat_name, node_names in pattern_node_categories_map.items():
        if name in node_names:
            return cat_name
    else:
        return 'deprecated'

@persistent
def rebuildOSLSystem(dummy):
    pass

    # context = bpy.context
    # scene = context.scene
    # if(scene.render.engine == 'PRMAN_RENDER'):
    #     for ob in scene.objects:
    #         for matSl in ob.material_slots:
    #             mat = matSl.material
    #             if(hasattr(mat, "renderman")):
    #                 if(mat.renderman.nodetree in bpy.data.node_groups):
    #                     nt = bpy.data.node_groups[mat.renderman.nodetree]
    #                     for node in nt.nodes:
    #                         if(node.bl_idname == "PxrOSLPatternNode"):
    #                             # Recompile the node.
    #                             node.RefreshNodes(context, node, mat, True)


# our own base class with an appropriate poll function,
# so the categories only show up in our own tree type
class RendermanPatternNodeCategory(NodeCategory):

    @classmethod
    def poll(cls, context):
        return context.space_data.tree_type == 'ShaderNodeTree'

classes = [
    RendermanShaderSocket,
    RendermanNodeSocketColor,
    RendermanNodeSocketFloat,
    RendermanNodeSocketInt,
    RendermanNodeSocketString,
    RendermanNodeSocketVector,
    RendermanNodeSocketStruct,
    OSLProps
]

nodetypes = {}
pattern_categories = {}
def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    user_preferences = bpy.context.user_preferences
    prefs = user_preferences.addons[__package__].preferences

    # Register pointer property if not already done
    if not hasattr(bpy.types.Scene, "OSLProps"):
        bpy.types.Scene.OSLProps = PointerProperty(
            type=OSLProps, name="Renderman OSL Settings")

    categories = {}

    for name, arg_file in args_files_in_path(prefs, None).items():
        vals = generate_node_type(prefs, name, ET.parse(arg_file).getroot())
        if vals:
            typename, nodetype = vals
            nodetypes[typename] = nodetype
    # need to specially make an osl node
    # generate_osl_node()

    node_cats = {
        'bxdf': ('PRMan Bxdfs', []),
        'light': ('PRMan Lights', []),
        'patterns_texture': ('PRMan Texture Patterns', []),
        'patterns_bump': ('PRMan Bump Patterns', []),
        'patterns_color': ('PRMan Color Patterns', []),
        'patterns_manifold': ('PRMan Manifold Patterns', []),
        'patterns_geometry': ('PRMan Geometry Patterns', []),
        'patterns_utility': ('PRMan Utility Patterns', []),
        'patterns_script': ('PRMan Script Patterns', []),
        'patterns_displace': ('PRMan Displacement Patterns', []),
        'patterns_layer': ('PRMan Layers', []),
        'displacement': ('PRMan Displacements', [])
    }

    for name, node_type in nodetypes.items():
        node_item = NodeItem(name, label=node_type.bl_label)
        
        if node_type.renderman_node_type == 'pattern':
            # insert pxr layer in bxdf
            pattern_cat = GetPatternCategory(node_type.bl_label)
            if pattern_cat == 'deprecated':
                continue
            node_cat = 'patterns_' + pattern_cat
            node_cats[node_cat][1].append(node_item)
            pattern_cat = pattern_cat.capitalize()
            if pattern_cat not in pattern_categories:
                pattern_categories[pattern_cat] = {}
            pattern_categories[pattern_cat][name] = node_type

        elif 'LM' in name and node_type.renderman_node_type == 'bxdf':
            #skip LM materials
            continue
        elif node_type.renderman_node_type == 'light' and 'PxrMeshLight' not in name:
            #skip light nodes
            continue
        else:
            node_cats[node_type.renderman_node_type][1].append(node_item)            

    # all categories in a list
    node_categories = [
        # identifier, label, items list
        RendermanPatternNodeCategory("PRMan_output_nodes", "PRMan Outputs",
                                     items=[NodeItem('RendermanOutputNode', label=RendermanOutputNode.bl_label)]),
    ]

    for name, (desc, items) in node_cats.items():
        node_categories.append(RendermanPatternNodeCategory(name, desc,
                                     items=sorted(items,
                                                  key=attrgetter('_label'))))

    nodeitems_utils.register_node_categories("RENDERMANSHADERNODES",
                                             node_categories)

    bpy.app.handlers.load_post.append(rebuildOSLSystem)


def unregister():
    nodeitems_utils.unregister_node_categories("RENDERMANSHADERNODES")
    # bpy.utils.unregister_module(__name__)
    bpy.app.handlers.load_post.remove(rebuildOSLSystem)

    for cls in classes:
        bpy.utils.unregister_class(cls)
