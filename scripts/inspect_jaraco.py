import jaraco.functools
print('jaraco version:', getattr(jaraco.functools,'__version__','n/a'))
print('has splat:', hasattr(jaraco.functools, 'splat'))
print('attrs:', [a for a in dir(jaraco.functools) if 'splat' in a or 'splat'==a])
