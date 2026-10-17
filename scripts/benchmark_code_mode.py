"""Compare fresh and lifespan-reused Code Mode workers on this machine."""
import argparse
import asyncio
import json
from contextlib import asynccontextmanager
from statistics import median
from time import perf_counter
from types import SimpleNamespace

from mcp.server.fastmcp import FastMCP
from proxmox_mcp.code_mode import install_code_mode


@asynccontextmanager
async def fresh_workers():
    yield


async def benchmark(iterations):
    results = {}
    for reuse in (False, True):
        mode = install_code_mode(SimpleNamespace(mcp=FastMCP('benchmark')))
        samples = []
        async with mode.pool_lifespan() if reuse else fresh_workers():
            for _ in range(iterations):
                start = perf_counter()
                result = await mode.execute('1 + 1')
                assert result['success'] and result['data']['result'] == 2
                samples.append((perf_counter() - start) * 1000)
        results['reused' if reuse else 'fresh'] = {'median_ms': round(median(samples), 3), 'iterations': iterations}
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iterations', type=int, default=20)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error('--iterations must be positive')
    asyncio.run(benchmark(args.iterations))
