import configparser
import itertools
import os

cfg = configparser.ConfigParser()
cfg.optionxform = str
cfg_folder = 'cfg'

demo_mode = 0

# experiment parameters
brdf_metallic = [0, 1]
brdf_roughness = [0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0]
brdf_ior = [1.00, 1.33, 1.54, 1.79, 2.41, 2.97]
object_shapes = [
    'sphere', 'blob01.obj', 'blob03.obj', 'blob06.obj', 'blob08.stl', 'bunny.ply',
    'buddha.ply', 'dragon.ply', 'donut.stl', 'donut3.stl', 'minotaur.stl',
    'wolf.stl', 'amfd21.obj', 'amfd28.stl', 'amfd31.stl', 'mathball.stl',
    'human.stl'
]
light_directions = ['L96.csv', 'L200.csv']
interreflections = [0]
cast_shadow = [0, 1]

# demo_mode parameters
if demo_mode:
    brdf_metallic = [0]
    brdf_roughness = [0.25, 0.55, 0.85]
    brdf_ior = [1.00, 1.54, 2.41, 5.00]
    object_shapes = [
        'sphere', 'blob01.obj', 'blob03.obj', 'bunny.ply', 'donut3.stl',
        'minotaur.stl', 'amfd21.obj'
    ]
    light_directions = ['L76.csv']
    interreflections = [0]
    cast_shadow = [0]

with open('arguments.txt', 'w') as txt:
    txt.write('')

if not os.path.exists(cfg_folder):
    os.makedirs(cfg_folder)

for bm, br, bi, sh, ld, ir, cs in itertools.product(
    brdf_metallic, brdf_roughness, brdf_ior, object_shapes, light_directions,
    interreflections, cast_shadow
):
    ld_filename = ld.split('.')[0]
    filename = 'm{}r{}i{}_{}_ir{}cs{}'.format(
        bm, int(br * 100), int(bi * 100), ld_filename, ir, cs)
    cfg['settings'] = {
        'object_file': f'{sh}',
        'working_dir': '../../working_dir',
        'out_dir': f'../../output_dir/{filename}',
    }
    if ir == 0:  # no interreflections
        bounces = [0, 0, 0, 0, 0]
    if ir == 1:  # direct light
        bounces = [8, 1, 2, 0, 8]
    if ir == 2:  # full global illumination
        bounces = [128, 128, 128, 128, 128]
    cfg['rendering'] = {
        'resolution_x': 640,
        'resolution_y': 480,
        'samples': 256,
        'max_bounces': f'{bounces[0]}',
        'min_bounces': 0,
        'glossy_bounces': f'{bounces[1]}',
        'transmission_bounces': f'{bounces[2]}',
        'volume_bounces': f'{bounces[3]}',
        'transparent_max_bounces': f'{bounces[4]}',
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
        'synchronize_with_views': 'True',
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
        'synchronize_with_views': 'True',
    }
    cfg['camera'] = {
        'model': 'orthographic',
        'focal_length': 50,
        'sensor_width': 36,
        'sensor_height': 24,
    }
    preset = 'object_sphere' if sh.lower() == 'sphere' else 'object_custom'
    cfg['object'] = {
        'preset': f'{preset}',
        'enable_multiple_views': 'False',
        'object_directions_file': 'view.csv',
        'enable_rendering_by_degree': 'True',
        'degree': 60,
    }
    no_shadow = 0 if cs == 1 else 1
    cfg['object_sphere'] = {
        'segments': 256,
        'ring_count': 128,
        'radius': 2,
        'location': '0, 0, 0',
        'rotation': '0, 0, 0',
        'use_smooth': 'True',
        'no_shadow': f'{no_shadow}',
        'subdivision_surface': 'False',
    }
    cfg['object_custom'] = {
        'location': '0, 0, 0',
        'rotation': '0, 0, 0',
        'max_dimension': 4,
        'geometry_to_origin': 'True',
        'use_smooth': 'True',
        'no_shadow': f'{no_shadow}',
    }
    cfg['shader'] = {
        'preset': 'material'
    }
    specular = ((bi - 1) / (bi + 1)) ** 2 / 0.08
    cfg['material'] = {
        'metallic': f'{bm}',
        'specular': f'{specular}',
        'roughness': f'{br}',
        'sheen': 0,
        'sheen_tint': 0.50,
        'ior': f'{bi}',
    }
    sh_filename = sh.split(".")[0]
    out_filename = f"{filename}_{sh_filename}.ini"
    with open(os.path.join(cfg_folder, out_filename), 'w') as config_file:
        cfg.write(config_file)
    with open('arguments.txt', 'a') as txt:
        txt.write(f'misc/{cfg_folder}/{out_filename}')
        txt.write(' ')
