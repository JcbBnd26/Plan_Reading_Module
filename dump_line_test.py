from backbone.chunking import Chunker

c = Chunker()
chunks = c.process("test.pdf")  # change if needed

print("\nTOTAL CHUNKS:", len(chunks))
print("FIRST 50 CHUNKS:\n")

for i, ch in enumerate(chunks[:50]):
    print(i+1, ch.bbox, ch.content)
