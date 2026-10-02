#!/usr/bin/env python3
"""
CLI Interface for AI Memory Service
"""

import sys
import json
import argparse
from datetime import datetime
from memory_service import AIMemoryService

def print_memory(memory):
    """Pretty print a memory object"""
    print(f"ID: {memory.id}")
    print(f"Type: {memory.type}")
    print(f"Created: {memory.created_at}")
    if memory.session_id:
        print(f"Session: {memory.session_id}")
    print(f"Content: {memory.content[:100]}...")
    print("-" * 50)

def main():
    # Initialize the memory service
    memory_service = AIMemoryService()

    parser = argparse.ArgumentParser(description='AI Memory Service CLI')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Store command
    store_parser = subparsers.add_parser('store', help='Store a new memory')
    store_parser.add_argument('--type', required=True, help='Memory type')
    store_parser.add_argument('--content', required=True, help='Memory content')
    store_parser.add_argument('--metadata', help='JSON metadata')
    store_parser.add_argument('--session-id', help='Session ID')
    store_parser.add_argument('--category', help='Memory category')

    # Retrieve command
    retrieve_parser = subparsers.add_parser('retrieve', help='Retrieve memories')
    retrieve_parser.add_argument('--limit', type=int, default=10, help='Number of memories to retrieve')

    # Search command
    search_parser = subparsers.add_parser('search', help='Search memories')
    search_parser.add_argument('--query', required=True, help='Search query')
    search_parser.add_argument('--limit', type=int, default=10, help='Number of results')
    search_parser.add_argument('--type', choices=['hybrid', 'vector', 'keyword'],
                              default='hybrid', help='Search type')
    search_parser.add_argument('--project', help='Only return memories tagged for this project path')
    search_parser.add_argument('--json', action='store_true', help='Return full memory records as JSON')

    # List command
    list_parser = subparsers.add_parser('list', help='List recent memories')
    list_parser.add_argument('--limit', type=int, default=20, help='Number of memories to show')
    list_parser.add_argument('--project', help='Only return memories tagged for this project path')

    # Get command
    get_parser = subparsers.add_parser('get', help='Get specific memory by ID')
    get_parser.add_argument('--id', type=int, required=True, help='Memory ID')

    # Update command
    update_parser = subparsers.add_parser('update', help='Update existing memory')
    update_parser.add_argument('--id', type=int, required=True, help='Memory ID')
    update_parser.add_argument('--content', help='New content')
    update_parser.add_argument('--metadata', help='New JSON metadata')
    update_parser.add_argument('--project', help='Require this project path to own the memory')

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete memory')
    delete_parser.add_argument('--id', type=int, required=True, help='Memory ID')
    delete_parser.add_argument('--project', help='Require this project path to own the memory')

    # Sessions command
    sessions_parser = subparsers.add_parser('sessions', help='List sessions')
    sessions_parser.add_argument('--limit', type=int, default=10, help='Number of sessions to show')

    # Stats command
    subparsers.add_parser('stats', help='Get memory system statistics')

    # Backup command
    backup_parser = subparsers.add_parser('backup', help='Backup memory database')

    restore_parser = subparsers.add_parser('restore', help='Restore SQLite from a validated backup and rebuild Chroma')
    restore_parser.add_argument('--backup-file', required=True, help='SQLite backup path')
    subparsers.add_parser('rebuild-index', help='Rebuild Chroma from SQLite')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == 'store':
            metadata = json.loads(args.metadata) if args.metadata else None
            memory_id = memory_service.store_memory(
                args.type,
                args.content,
                metadata,
                args.session_id,
                args.category
            )
            if memory_id:
                print(f"Memory stored with ID: {memory_id}")
            else:
                print("Failed to store memory")

        elif args.command == 'retrieve':
            memories = memory_service.search_memory("", limit=args.limit)
            for memory in memories:
                print_memory(memory)

        elif args.command == 'search':
            memories = memory_service.search_memory(
                args.query,
                limit=args.limit,
                search_type=args.type
            )
            if args.project:
                memories = [m for m in memories if m.metadata.get('project') == args.project or m.metadata.get('scope') == 'global' or m.metadata.get('global') is True]
            if args.json:
                print(json.dumps([
                    {'id': m.id, 'type': m.type, 'content': m.content,
                     'metadata': m.metadata, 'created_at': m.created_at,
                     'session_id': m.session_id}
                    for m in memories
                ], default=str))
            else:
                print(f"Found {len(memories)} memories:")
                for memory in memories:
                    print_memory(memory)

        elif args.command == 'list':
            import sqlite3
            conn = sqlite3.connect(memory_service.db_path)
            cursor = conn.cursor()
            if args.project:
                cursor.execute('''SELECT id, type, content, metadata, created_at, session_id
                                  FROM memories WHERE json_extract(metadata, '$.project') = ?
                                    OR json_extract(metadata, '$.scope') = 'global'
                                    OR json_extract(metadata, '$.global') = 1
                                  ORDER BY created_at DESC LIMIT ?''',
                               (args.project, max(1, args.limit)))
            else:
                cursor.execute('''SELECT id, type, content, metadata, created_at, session_id
                                  FROM memories ORDER BY created_at DESC LIMIT ?''',
                               (max(1, args.limit),))
            rows = cursor.fetchall()
            conn.close()
            memories = [
                {'id': row[0], 'type': row[1], 'content': row[2],
                 'metadata': json.loads(row[3]) if row[3] else {},
                 'created_at': row[4], 'session_id': row[5]}
                for row in rows
            ]
            print(json.dumps(memories, indent=2))

        elif args.command == 'get':
            memory = memory_service.get_memory(args.id)
            if memory:
                print_memory(memory)
            else:
                print(f"No memory found with ID {args.id}")

        elif args.command == 'update':
            metadata = json.loads(args.metadata) if args.metadata else None
            if args.project:
                existing = memory_service.get_memory(args.id)
                if not existing or not (
                    existing.metadata.get('project') == args.project
                    or existing.metadata.get('scope') == 'global'
                    or existing.metadata.get('global') is True
                ):
                    print('Memory not found in this project')
                    return
            success = memory_service.update_memory(
                args.id,
                content=args.content,
                metadata=metadata
            )
            if success:
                print("Memory updated successfully")
            else:
                print("Failed to update memory")

        elif args.command == 'delete':
            if args.project:
                existing = memory_service.get_memory(args.id)
                if not existing or not (
                    existing.metadata.get('project') == args.project
                    or existing.metadata.get('scope') == 'global'
                    or existing.metadata.get('global') is True
                ):
                    print('Memory not found in this project')
                    return
            success = memory_service.delete_memory(args.id)
            if success:
                print("Memory deleted successfully")
            else:
                print("Failed to delete memory")

        elif args.command == 'sessions':
            sessions = memory_service.list_sessions(args.limit)
            for session in sessions:
                print(f"ID: {session['id']}")
                print(f"Start: {session['start_time']}")
                if session['end_time']:
                    print(f"End: {session['end_time']}")
                print(f"Description: {session['description']}")
                print("-" * 50)

        elif args.command == 'stats':
            stats = memory_service.get_memory_stats()
            print(json.dumps(stats, indent=2, default=str))

        elif args.command == 'backup':
            success = memory_service.backup_memory_database()
            if success:
                print("Database backed up successfully")
            else:
                print("Backup failed")

        elif args.command == 'restore':
            success = memory_service.restore_memory_database(args.backup_file)
            if success:
                print("Database restored; Chroma rebuild attempted from SQLite")
            else:
                print("Restore failed")

        elif args.command == 'rebuild-index':
            print("Vector index rebuilt from SQLite" if memory_service.rebuild_vector_index() else "Vector index rebuild failed")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
