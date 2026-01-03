from backbone.chunking import Chunker

c = Chunker()

# Change "test.pdf" to the name of a real PDF in the same folder
results = c.process("test.pdf")

for r in results:
    print(r)
    print("bbox:", r.bbox)
    print("type:", r.type)
    print("content:", r.content[:120])
    print("---")
