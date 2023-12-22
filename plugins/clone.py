#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# vim:fenc=utf-8

"""
Clone the contents of a source pipe into a new target.
"""

import json
import copy
from datetime import datetime, timedelta
from typing import Any, Iterator, Dict, Optional, Union
import meerschaum as mrsm
from meerschaum.utils.debug import dprint
from meerschaum.utils.warnings import warn, info
from meerschaum.utils.misc import round_time

__version__ = '0.1.3'

def register(pipe: mrsm.Pipe) -> Dict[str, Any]:
    """
    Prompt the user for the source pipe.
    """
    from meerschaum.utils.interactive import select_pipes
    sources = pipe.parameters.get('sources', [pipe.parameters.get('source'), {}])
    src_pipes = (
        select_pipes()
        if not any(sources)
        else [mrsm.Pipe(**source['pipe']) for source in sources]
    )
    columns = {
        '__connector_keys': '__connector_keys',
        '__metric_key'    : '__metric_key',
        '__location_key'  : '__location_key',
        '__instance_keys' : '__instance_keys',
    }
    for src_pipe in src_pipes:
        columns.update(src_pipe.columns)
    return {
        'sources': [
            {
                'pipe': src_pipe.meta,
                'params': {},
                'chunk_minutes': 1440,
                'backtrack_minutes': 1440,
            }
            for src_pipe in src_pipes
        ],
        'columns': columns,
    }


def fetch(
        pipe: mrsm.Pipe,
        begin: Union[datetime, int, None] = None,
        end: Union[datetime, int, None] = None,
        debug: bool = False,
        **kwargs: Any
    ) -> Iterator['pd.DataFrame']:
    """
    Fetch the contents of the source pipe.
    """
    sources = pipe.parameters.get('sources', [pipe.parameters.get('source', {})])
    if not sources or not any(sources):
        raise Exception(f"Missing source for {pipe}.")

    skip_pipe_keys = sources[0].get('skip_pipe_keys', False)
    if not skip_pipe_keys:
        pipe.columns.update({
            '__connector_keys': '__connector_keys',
            '__metric_key'    : '__metric_key',
            '__location_key'  : '__location_key',
            '__instance_keys' : '__instance_keys',
        })

    for source in sources:
        if 'pipe' not in source:
            warn(f"Missing 'pipe' in source for {pipe}, skipping...", stack=False)
            continue
        src_pipe = mrsm.Pipe(**source['pipe'])
        params = source.get('params', {})
        if not src_pipe.exists(debug=debug):
            warn(f"Missing source {src_pipe} (of {pipe}), skipping...", stack=False)
            continue
        dt_col = src_pipe.columns.get('datetime', None)

        pipe.columns.update(src_pipe.columns)

        select_columns = source.get('select_columns', None)
        omit_columns = source.get('omit_columns', None)
        backtrack_minutes = source.get('backtrack_minutes', 1440)
        chunk_minutes = source.get('chunk_minutes', 1440)
        src_begin = begin or get_source_begin(
            pipe,
            src_pipe,
            params = params,
            skip_pipe_keys = skip_pipe_keys,
            debug = debug,
        )
        if not begin and src_begin is not None:
            src_begin = apply_backtrack_minutes(src_begin, backtrack_minutes)
        if isinstance(src_begin, datetime):
            src_begin = round_time(src_begin, timedelta(minutes=chunk_minutes))

        src_end = end or (
            src_pipe.get_sync_time(params=params, debug=debug)
            if dt_col is not None
            else None
        )
        if src_end is not None:
            src_end = apply_backtrack_minutes(src_end, -1)
        if isinstance(src_end, datetime):
            src_end = round_time(src_end, timedelta(minutes=chunk_minutes), to='up')

        chunks = src_pipe.get_data(
            select_columns = select_columns,
            omit_columns = omit_columns,
            params = params,
            begin = src_begin,
            end = src_end,
            chunk_interval = get_chunk_interval(src_pipe, chunk_minutes),
            as_iterator = (dt_col is not None),
            debug = debug,
        )
        if dt_col is None:
            chunks = [chunks]
        for chunk in chunks:
            if not skip_pipe_keys:
                chunk['__connector_keys'] = str(src_pipe.connector_keys)
                chunk['__metric_key']     = str(src_pipe.metric_key)
                chunk['__location_key']   = str(src_pipe.location_key)
                chunk['__instance_keys']  = str(src_pipe.instance_keys)

            if not chunk.empty:
                yield chunk


def get_source_begin(
        pipe: mrsm.Pipe,
        src_pipe: mrsm.Pipe,
        params: Optional[Dict[str, Any]] = None,
        skip_pipe_keys: bool = False,
        debug: bool = False,
    ) -> Union[datetime, int, None]:
    """
    If `--begin` is not explicitly stated, determine the beginning timestamp for this source.

    Parameters
    ----------
    pipe: mrsm.Pipe
        The target clone pipe being synced.

    source_pipe: mrsm.Pipe
        The source pipe from which to fetch data.

    params: Optional[Dict[str, Any]], default None
        Parameter-level parameters to search against the source pipe.

    skip_pipe_keys: bool, default False
        If `True`, do not include source-pipes' keys in the query.

    Returns
    -------
    A `datetime` or `int` timestamp from which to begin syncing.
    There is a possibility of `None` if the source pipe does not exist.
    """
    dt_col = pipe.columns.get('datetime', None)
    if dt_col is None:
        return None
    src_params = copy.deepcopy((params or {}))
    dest_params = copy.deepcopy(src_params)
    if not skip_pipe_keys:
        dest_params.update({
            '__connector_keys': str(src_pipe.connector_keys),
            '__metric_key'    : str(src_pipe.metric_key),
            '__location_key'  : str(src_pipe.location_key),
            '__instance_keys' : str(src_pipe.instance_keys),
        })
    return (
        pipe.get_sync_time(params=dest_params, debug=debug)
        or
        src_pipe.get_sync_time(newest=False, params=src_params, debug=debug)
    )


def apply_backtrack_minutes(
        timestamp: Union[datetime, int],
        backtrack_minutes: int,
    ) -> Union[datetime, int]:
    """
    Apply the backtrack interval to the given timestamp.

    Parameters
    ----------
    timestamp: Union[datetime, int]
        The timestamp to which to apply the backtrack interval.

    backtrack_minutes: int
        The number of minutes (or values if `timestamp` is an `int`) to subtract from `timestamp`.

    Returns
    -------
    A new timestamp value of the same input type less the BTI.
    """
    return (
        (timestamp - timedelta(minutes=backtrack_minutes))
        if isinstance(timestamp, datetime)
        else timestamp - backtrack_minutes
    )


def get_chunk_interval(source_pipe: mrsm.Pipe, chunk_minutes: int) -> Union[timedelta, int, None]:
    """
    Return the appropriate chunk interval to read from the source pipe.
    """
    dt_col = source_pipe.columns.get('datetime', None)
    if dt_col is None:
        return None
    return (
        timedelta(minutes=chunk_minutes)
        if 'datetime' in source_pipe.dtypes.get(dt_col, 'datetime').lower()
        else chunk_minutes
    )
