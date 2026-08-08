# Решение КЕГЭ №15
def f(x, A):
    return (x & 29 != 0) <= ((x & 17 == 0) <= (x & A != 0))

for A in range(1, 1000):
    if all(f(x, A) for x in range(1000)):
        print(A)
        break
