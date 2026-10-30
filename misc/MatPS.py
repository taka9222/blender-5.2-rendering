import configparser
import itertools
import os
import random

cfg = configparser.ConfigParser()
cfg.optionxform = str
cfg_folder = 'cfg'

# experiment parameters
object_shapes = [
    'sphere', 'blob01.obj', 'donut3.stl', 'amfd28.stl', 'amfd31.stl',
    'mathball.stl', 'human.stl'
]
light_directions = ['L96.csv']
interreflections = [2]
cast_shadow = [1]

with open('arguments.txt', 'w') as txt:
    txt.write('')

if not os.path.exists(cfg_folder):
    os.makedirs(cfg_folder)

for midx, sh, ld, ir, cs in itertools.product(
    range(150), object_shapes, light_directions, interreflections, cast_shadow
):
    ld_filename = ld.split(".")[0]
    filename = f'mat{midx}_{ld_filename}_ir{ir}cs{cs}'
    cfg['settings'] = {
        'object_file': f'{sh}',
        'working_dir': '../../working_dir',
        'out_dir': f'../../MatPS/{filename}'
    }
    cfg['rendering'] = {
        'resolution_x': 640,
        'resolution_y': 480,
        'samples': 256,
        'max_bounces': 128,
        'min_bounces': 0,
        'glossy_bounces': 128,
        'transmission_bounces': 128,
        'volume_bounces': 128,
        'transparent_max_bounces': 128,
        'transparent_min_bounces': 0,
        'device': 'CPU',
        'denoising': 'False',
        'denoising_legacy': 'False',
        'color_mode': 'BW',
        'background_color': '0, 0, 0',
        'disable_anti_aliasing': 'True',
        'transparent_background': 'False',
        'use_hdri': 'None',
        'no_background': 'True',
        'hdri_offset': 0.00,
        'synchronize_with_views': 'True'
    }
    cfg['light'] = {
        'model': 'distant',
        'energy': 1,
        'SUN_angle': 0.00918,
        'POINT_size': 0.25,
        'amount': 1,
        'light_directions_file': f'{ld}',
        'file_normalization': 'False',
        'enable_rendering_by_degree': 'False',
        'degree': 360,
        'POINT_radius': 5,
        'synchronize_with_views': 'True'
    }
    cfg['camera'] = {
        'model': 'orthographic',
        'focal_length': 50,
        'sensor_width': 36,
        'sensor_height': 24
    }
    preset = 'object_sphere' if sh.lower() == 'sphere' else 'object_custom'
    cfg['object'] = {
        'preset': f'{preset}',
        'enable_multiple_views': 'False',
        'object_directions_file': 'view.csv',
        'enable_rendering_by_degree': 'True',
        'degree': 60
    }
    no_shadow = 0 if cs == 1 else 1
    cfg['object_sphere'] = {
        'segments': 256,
        'ring_count': 128,
        'radius': 2,
        'location': '0, 0, 0',
        'rotation': '0, 0, 0',
        'use_smooth': 'True',
        'no_shadow': 0,
        'subdivision_surface': 'False'
    }
    cfg['object_custom'] = {
        'location': '0, 0, 0',
        'rotation': '0, 0, 0',
        'max_dimension': 4,
        'geometry_to_origin': 'True',
        'use_smooth': 'True',
        'no_shadow': 0
    }
    cfg['shader'] = {
        'preset': 'material'
    }
    color = random.randint(0, 64) + 172
    s_flag = abs(random.randint(0, 2) - 1)
    if s_flag:
        specular = random.random() * 2. + 1.
    else:
        specular = random.random()
    r_flag = max(0, random.randint(0, 2) - 1)
    cfg['material'] = {
        'base_color': '{0}, {0}, {0}'.format(color),
        'metallic': f'{max(0, random.randint(0, 2) - 1)}',
        'specular': f'{specular}',
        'roughness': f'{(random.random() + r_flag) * 0.5}',
        'sheen': 0
    }
    sh_filename = sh.split(".")[0]
    out_filename = f"{filename}_{sh_filename}.ini"
    with open(os.path.join(cfg_folder, out_filename), 'w') as config_file:
        cfg.write(config_file)
    with open('arguments.txt', 'a') as txt:
        txt.write(f'misc/{cfg_folder}/{out_filename}')
        txt.write(' ')
