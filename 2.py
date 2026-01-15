print('x y z w | F')

for x in range(2):
    for y in range(2):
        for z in range(2):
            for w in range(2):
                F = x or ((not(y)) or z or w) and (y or (not(w)))
                if F == 0:
                    print(x, y, z, w, '|', int(F))
