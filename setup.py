from setuptools import setup, find_packages

setup(
    name='Toolsbase',
    version='0.1',
    description='The local avaliable toolkits', 
    packages=[  # partially installation
        'basetool',
        'object_detector',
        'advanced_object_detector',
        'text_detector'
    ],
    
    package_dir={'': 'tools'}     # from xx import xx ;instead of from tools.xx import xx
    # modify logical root path
)