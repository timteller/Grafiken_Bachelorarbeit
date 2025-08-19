#!/usr/bin/env python3
import xml.etree.ElementTree as ET
import os
import re
import argparse
from copy import deepcopy
from collections import defaultdict

def sanitize_filename(name: str) -> str:
    """Sanitize a string to be safe for use as a filename."""
    if name is None or name == "":
        name = "Unnamed_Layer"
    return re.sub(r'[^\w\-_\.]+', '_', name).strip("_")

def _find_first_diagram(root: ET.Element) -> ET.Element:
    """Return the first <diagram> element; raise if missing."""
    diagram = root.find('diagram')
    if diagram is None:
        raise ValueError("No <diagram> element found in the input file.")
    return diagram

def _get_mxgraphmodel(diagram: ET.Element) -> ET.Element:
    """Return the <mxGraphModel> under a diagram; raise if missing."""
    mx_graph_model = diagram.find('mxGraphModel')
    if mx_graph_model is None:
        # fallback: search anywhere under diagram
        mx_graph_model = diagram.find('.//mxGraphModel')
    if mx_graph_model is None:
        raise ValueError("No <mxGraphModel> found in the input file.")
    return mx_graph_model

def _get_root_container(mx_graph_model: ET.Element) -> ET.Element:
    """Return the <root> element under mxGraphModel; raise if missing."""
    mx_root = mx_graph_model.find('root')
    if mx_root is None:
        raise ValueError("No <root> element under <mxGraphModel>.")
    return mx_root

def _collect_index(mx_root: ET.Element):
    """
    Build indices:
      - id_index: id -> element
      - children_index: parent_id -> [elements]
    These indices include all descendants under <root>.
    """
    id_index = {}
    children_index = defaultdict(list)

    for elem in mx_root.iter():
        elem_id = elem.attrib.get('id')
        if elem_id:
            id_index[elem_id] = elem
        parent_id = elem.attrib.get('parent')
        if parent_id:
            children_index[parent_id].append(elem)

    return id_index, children_index

def _deepcopy_with_children(elem: ET.Element) -> ET.Element:
    """Deep copy an element including all subelements."""
    return deepcopy(elem)

def _copy_required_base_cells(mx_root_src: ET.Element, mx_root_dst: ET.Element):
    """
    Copy structural base cells (id="0" and id="1") if present.
    Some renderers expect both.
    """
    for base_id in ("0", "1"):
        base = mx_root_src.find(f'.//*[@id="{base_id}"]')
        if base is not None:
            mx_root_dst.append(_deepcopy_with_children(base))

def _bfs_collect_subtree(start_ids, children_index):
    """
    Traverse by parent relationship starting from start_ids.
    Return the set of all element ids to copy (including start_ids).
    """
    to_copy_ids = set()
    queue = list(start_ids)

    while queue:
        cur_id = queue.pop(0)
        if cur_id in to_copy_ids:
            continue
        to_copy_ids.add(cur_id)
        for child in children_index.get(cur_id, []):
            child_id = child.attrib.get('id')
            if child_id:
                queue.append(child_id)
    return to_copy_ids

def _export_single_layer(layer_elem: ET.Element,
                         mxfile_root_src: ET.Element,
                         diagram_src: ET.Element,
                         mx_graph_model_src: ET.Element,
                         mx_root_src: ET.Element,
                         id_index,
                         children_index,
                         output_dir: str):
    """
    Build a new mxfile containing only the selected layer and its transitive descendants.
    """
    layer_id = layer_elem.attrib.get('id')
    layer_label = layer_elem.attrib.get('value') or 'Unnamed_Layer'

    # Create new mxfile root with preserved metadata where possible
    new_mxfile = ET.Element('mxfile', attrib={
        'host': mxfile_root_src.attrib.get('host', 'app.diagrams.net'),
        'agent': mxfile_root_src.attrib.get('agent', ''),
        'version': mxfile_root_src.attrib.get('version', '28.0.7')
    })

    # Create diagram element (reuse original id if present)
    new_diagram = ET.SubElement(new_mxfile, 'diagram', attrib={
        'name': layer_label,
        'id': diagram_src.attrib.get('id', 'default_id')
    })

    # Create mxGraphModel with same attributes as source
    new_mx_graph_model = ET.SubElement(new_diagram, 'mxGraphModel', attrib=mx_graph_model_src.attrib)
    new_mx_root = ET.SubElement(new_mx_graph_model, 'root')

    # Copy structural base cells (id="0" and id="1")
    _copy_required_base_cells(mx_root_src, new_mx_root)

    # Copy the layer cell itself
    new_mx_root.append(_deepcopy_with_children(layer_elem))

    # Collect the entire subtree of elements whose parent is in the growing set
    to_copy_ids = _bfs_collect_subtree({layer_id}, children_index)

    # Insert every element found (excluding ones already added by base cells and the layer itself to avoid dupes)
    already_added = {e.attrib.get('id') for e in new_mx_root.findall('.//*') if e.attrib.get('id')}
    for elem_id in to_copy_ids:
        if elem_id in already_added:
            continue
        elem = id_index.get(elem_id)
        if elem is None:
            continue
        # Only copy if its parent is in to_copy_ids or it's the layer itself
        parent_id = elem.attrib.get('parent')
        if parent_id in to_copy_ids or elem_id == layer_id:
            new_mx_root.append(_deepcopy_with_children(elem))
            already_added.add(elem_id)

    # Write out
    os.makedirs(output_dir, exist_ok=True)
    output_filename = sanitize_filename(layer_label) + '.drawio'
    output_path = os.path.join(output_dir, output_filename)
    ET.ElementTree(new_mxfile).write(output_path, encoding='utf-8', xml_declaration=True)
    print(f"Exported layer '{layer_label}' to '{output_path}'")

def export_layers(input_file: str, output_dir: str):
    """
    Export each layer of a Draw.io (.drawio) file into separate .drawio files.
    Fixes:
      - Deep-copy all elements (no mutation of source tree).
      - Include structural base cells id=0 and id=1.
      - Traverse transitive parent->children relations (captures edge labels with parent=edge-id).
      - Preserve full geometry/style subtrees.
    External behavior (CLI, outputs) remains the same.
    """
    # Parse the input XML file
    tree = ET.parse(input_file)
    root = tree.getroot()

    # Locate first diagram and its mxGraphModel/root
    diagram_src = _find_first_diagram(root)
    mx_graph_model_src = _get_mxgraphmodel(diagram_src)
    mx_root_src = _get_root_container(mx_graph_model_src)

    # Index elements for efficient traversal
    id_index, children_index = _collect_index(mx_root_src)

    # Identify layers: mxCell with parent="0"
    layers = [e for e in mx_root_src.findall('.//mxCell[@parent="0"]')]
    if not layers:
        raise ValueError("No layers found (no mxCell with parent='0').")

    # Export each layer
    for layer_elem in layers:
        _export_single_layer(
            layer_elem=layer_elem,
            mxfile_root_src=root,
            diagram_src=diagram_src,
            mx_graph_model_src=mx_graph_model_src,
            mx_root_src=mx_root_src,
            id_index=id_index,
            children_index=children_index,
            output_dir=output_dir
        )

def main():
    parser = argparse.ArgumentParser(description='Export layers from a drawio file.')
    parser.add_argument('--input_file', required=True, help='Path to the input .drawio file')
    parser.add_argument('--output_dir', required=True, help='Directory to save output files')
    args = parser.parse_args()
    export_layers(args.input_file, args.output_dir)

if __name__ == '__main__':
    main()
