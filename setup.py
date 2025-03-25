from setuptools import setup, find_packages

setup(
    name='Toolsbase',
    version='0.1',
    description='My local avaliable toolkits',
    #packages=find_packages('tools'),  
    packages=[  # partially installation
        'object_detector',
        'advanced_object_detector',
        'relevant_patch_zoomer',
        'text_detector'
    ],
    
    package_dir={'': 'tools'},     # from xx import xx ;instead of from tools.xx import xx
    # modify logical root path
)