import struct

# Precompute Mu-law decoding table (8-bit mu-law to 16-bit signed PCM)
# According to ITU-T G.711 μ-law decoding specifications:
#   linear = ((mantissa << 3) + 132) << exponent - 132
DECODE_TABLE = []
for i in range(256):
    # Bitwise inversion is standard for G.711 transmission representation
    mu = ~i & 0xFF
    sign = mu & 0x80
    exponent = (mu >> 4) & 0x07
    mantissa = mu & 0x0F
    
    val = ((mantissa << 3) + 132) << exponent
    val -= 132
    
    if sign:
        DECODE_TABLE.append(-val)
    else:
        DECODE_TABLE.append(val)

# Precompute Mu-law encoding table (16-bit signed PCM to 8-bit mu-law)
# According to ITU-T G.711 μ-law encoding specifications:
#   Use bias of 132, clipping at 32635, segment selection, and bitwise inversion.
ENCODE_TABLE = []
for sample in range(-32768, 32768):
    sign = 0x80 if sample < 0 else 0
    val = abs(sample)
    if val > 32635:
        val = 32635
    val += 132
    
    # Find segment (exponent)
    if val < 256:
        exponent = 0
    elif val < 512:
        exponent = 1
    elif val < 1024:
        exponent = 2
    elif val < 2048:
        exponent = 3
    elif val < 4096:
        exponent = 4
    elif val < 8192:
        exponent = 5
    elif val < 16384:
        exponent = 6
    else:
        exponent = 7
        
    mantissa = (val >> (exponent + 3)) & 0x0F
    mu = ~(sign | (exponent << 4) | mantissa) & 0xFF
    ENCODE_TABLE.append(mu)

def ulaw_to_pcm(ulaw_data: bytes) -> bytes:
    """Converts G.711 mu-law (8-bit) bytes to 16-bit linear signed PCM bytes."""
    pcm_samples = [DECODE_TABLE[b] for b in ulaw_data]
    return struct.pack(f"<{len(pcm_samples)}h", *pcm_samples)

def pcm_to_ulaw(pcm_data: bytes) -> bytes:
    """Converts 16-bit linear signed PCM bytes to G.711 mu-law (8-bit) bytes."""
    num_samples = len(pcm_data) // 2
    samples = struct.unpack(f"<{num_samples}h", pcm_data)
    # Translate and offset index (-32768 maps to index 0)
    ulaw_samples = [ENCODE_TABLE[s + 32768] for s in samples]
    return bytes(ulaw_samples)

def resample_pcm(pcm_data: bytes, from_rate: int, to_rate: int) -> bytes:
    """Resamples 16-bit signed linear PCM bytes between rates using linear interpolation."""
    if from_rate == to_rate or not pcm_data:
        return pcm_data
    
    num_samples = len(pcm_data) // 2
    samples = struct.unpack(f"<{num_samples}h", pcm_data)
    
    ratio = from_rate / to_rate
    new_num_samples = int(num_samples * (to_rate / from_rate))
    new_samples = []
    
    for i in range(new_num_samples):
        pos = i * ratio
        idx = int(pos)
        frac = pos - idx
        if idx >= num_samples - 1:
            val = samples[num_samples - 1]
        else:
            val = int(samples[idx] * (1 - frac) + samples[idx + 1] * frac)
        new_samples.append(val)
        
    return struct.pack(f"<{len(new_samples)}h", *new_samples)
