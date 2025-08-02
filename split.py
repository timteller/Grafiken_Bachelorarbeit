import xml.etree.ElementTree as ET
import os
import re
import argparse

def sanitize_filename(name):
    """Sanitize a string to be safe for use as a filename."""
    return re.sub(r'[^\w\-_\.]', '_', name)

def export_layers(input_file, output_dir):
    """Export each layer of a Draw.io file into separate Draw.io files."""
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Parse the input XML file
    tree = ET.parse(input_file)
    root = tree.getroot()
    
    # Find the mxGraphModel (assuming it's under the first diagram)
    mx_graph_model = root.find('.//mxGraphModel')
    if mx_graph_model is None:
        raise ValueError("No mxGraphModel found in the input file.")
    
    # Find all layer objects (objects with style="layer")
    # layers = mx_graph_model.findall('.//object[@style="layer"]')
    layers = mx_graph_model.findall('.//mxCell[@parent="0"]')
    if not layers:
        raise ValueError("No layers found in the input file.")
    
    for layer in layers:
        layer_id = layer.get('id')
        layer_label = layer.get('value', 'Unnamed_Layer[Script]')
        
        # Create a new XML tree for the output file
        new_root = ET.Element('mxfile', attrib={
            'host': root.get('host', 'app.diagrams.net'),
            'agent': root.get('agent', ''),
            'version': root.get('version', '28.0.7')
        })
        
        # Create a new diagram element
        new_diagram = ET.SubElement(new_root, 'diagram', attrib={
            'name': layer_label,
            'id': root.find('diagram').get('id', 'default_id')
        })
        
        # Create a new mxGraphModel
        new_mx_graph_model = ET.SubElement(new_diagram, 'mxGraphModel', attrib=mx_graph_model.attrib)
        
        # Create the root element under mxGraphModel
        new_mx_root = ET.SubElement(new_mx_graph_model, 'root')
        
        # Copy the default mxCell with id="0"
        default_cell = mx_graph_model.find('.//mxCell[@id="0"]')
        if default_cell is not None:
            ET.SubElement(new_mx_root, 'mxCell', attrib=default_cell.attrib)
        
        # Copy the layer object itself
        new_layer_cell = ET.SubElement(new_mx_root, 'mxCell', attrib=layer.attrib)

        # Find all elements that belong to this layer (those with parent=layer_id)
        layer_elements = mx_graph_model.findall(f'.//*[@parent="{layer_id}"]')
        
        # Copy these elements to the new root
        for element in layer_elements:
            new_element = ET.SubElement(new_mx_root, element.tag, attrib=element.attrib)
            for child in element:
                new_element.append(child)
        
        # Create a new tree and write to file
        new_tree = ET.ElementTree(new_root)
        output_filename = sanitize_filename(layer_label) + '.drawio'
        output_path = os.path.join(output_dir, output_filename)
        new_tree.write(output_path, encoding='utf-8', xml_declaration=True)
        print(f"Exported layer '{layer_label}' to '{output_path}'")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Export layers from a drawio file.')
    parser.add_argument('--input_file', required=True, help='Path to the input .drawio file')
    parser.add_argument('--output_dir', required=True, help='Directory to save output files')
    args = parser.parse_args()

    export_layers(args.input_file, args.output_dir)
