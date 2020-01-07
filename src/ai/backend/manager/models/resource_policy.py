from collections import OrderedDict
import logging
from typing import Any, Sequence

from aiohttp import web
from aiopg.sa.connection import SAConnection
import graphene
from graphene.types.datetime import DateTime as GQLDateTime
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pgsql
import trafaret as t

from ai.backend.common.logging import BraceStyleAdapter
from ai.backend.common.types import DefaultForUnspecified, ResourceSlot
from ai.backend.gateway.exceptions import InvalidAPIParameters
from .base import (
    metadata, BigInt, EnumType, ResourceSlotColumn,
    privileged_mutation,
    simple_db_mutate,
    simple_db_mutate_returning_item,
    set_if_set,
)
from .keypair import keypairs
from .user import UserRole

log = BraceStyleAdapter(logging.getLogger('ai.backend.manager.models'))

__all__: Sequence[str] = (
    'keypair_resource_policies',
    'KeyPairResourcePolicy',
    'DefaultForUnspecified',
    'CreateKeyPairResourcePolicy',
    'ModifyKeyPairResourcePolicy',
    'DeleteKeyPairResourcePolicy',
)


keypair_resource_policies = sa.Table(
    'keypair_resource_policies', metadata,
    sa.Column('name', sa.String(length=256), primary_key=True),
    sa.Column('created_at', sa.DateTime(timezone=True),
              server_default=sa.func.now()),
    sa.Column('default_for_unspecified',
              EnumType(DefaultForUnspecified),
              default=DefaultForUnspecified.LIMITED,
              nullable=False),
    sa.Column('total_resource_slots', ResourceSlotColumn(), nullable=False),
    sa.Column('max_concurrent_sessions', sa.Integer(), nullable=False),
    sa.Column('max_containers_per_session', sa.Integer(), nullable=False),
    sa.Column('max_vfolder_count', sa.Integer(), nullable=False),
    sa.Column('max_vfolder_size', sa.BigInteger(), nullable=False),
    sa.Column('idle_timeout', sa.BigInteger(), nullable=False),
    sa.Column('allowed_vfolder_hosts', pgsql.ARRAY(sa.String), nullable=False),
    sa.Column('allowed_docker_registries', pgsql.ARRAY(sa.String), nullable=False, default='{}'),
    # TODO: implement with a many-to-many association table
    # sa.Column('allowed_scaling_groups', sa.Array(sa.String), nullable=False),
)


class KeyPairResourcePolicy(graphene.ObjectType):
    name = graphene.String()
    created_at = GQLDateTime()
    default_for_unspecified = graphene.String()
    total_resource_slots = graphene.JSONString()
    max_concurrent_sessions = graphene.Int()
    max_containers_per_session = graphene.Int()
    idle_timeout = BigInt()
    max_vfolder_count = graphene.Int()
    max_vfolder_size = BigInt()
    allowed_vfolder_hosts = graphene.List(lambda: graphene.String)
    allowed_docker_registries = graphene.List(lambda: graphene.String)

    @classmethod
    def from_row(cls, row):
        if row is None:
            return None
        return cls(
            name=row['name'],
            created_at=row['created_at'],
            default_for_unspecified=row['default_for_unspecified'].name,
            total_resource_slots=row['total_resource_slots'].to_json(),
            max_concurrent_sessions=row['max_concurrent_sessions'],
            max_containers_per_session=row['max_containers_per_session'],
            idle_timeout=row['idle_timeout'],
            max_vfolder_count=row['max_vfolder_count'],
            max_vfolder_size=row['max_vfolder_size'],
            allowed_vfolder_hosts=row['allowed_vfolder_hosts'],
            allowed_docker_registries=row['allowed_docker_registries'],
        )

    @classmethod
    async def load_all(cls, context):
        async with context['dbpool'].acquire() as conn:
            query = (sa.select([keypair_resource_policies])
                       .select_from(keypair_resource_policies))
            result = await conn.execute(query)
            rows = await result.fetchall()
            return [cls.from_row(r) for r in rows]

    @classmethod
    async def load_all_user(cls, context, access_key):
        async with context['dbpool'].acquire() as conn:
            query = (sa.select([keypairs.c.user_id])
                       .select_from(keypairs)
                       .where(keypairs.c.access_key == access_key))
            result = await conn.execute(query)
            row = await result.fetchone()
            user_id = row['user_id']
            j = sa.join(
                keypairs, keypair_resource_policies,
                keypairs.c.resource_policy == keypair_resource_policies.c.name
            )
            query = (sa.select([keypair_resource_policies])
                       .select_from(j)
                       .where((keypairs.c.user_id == user_id)))
            result = await conn.execute(query)
            rows = await result.fetchall()
            return [cls.from_row(r) for r in rows]

    @classmethod
    async def batch_load_by_name(cls, context, names):
        async with context['dbpool'].acquire() as conn:
            query = (sa.select([keypair_resource_policies])
                       .select_from(keypair_resource_policies)
                       .where(keypair_resource_policies.c.name.in_(names))
                       .order_by(keypair_resource_policies.c.name))
            objs_per_key = OrderedDict()
            for k in names:
                objs_per_key[k] = None
            async for row in conn.execute(query):
                o = cls.from_row(row)
                objs_per_key[row.name] = o
        return tuple(objs_per_key.values())

    @classmethod
    async def batch_load_by_name_user(cls, context, names):
        async with context['dbpool'].acquire() as conn:
            access_key = context['access_key']
            j = sa.join(
                keypairs, keypair_resource_policies,
                keypairs.c.resource_policy == keypair_resource_policies.c.name
            )
            query = (sa.select([keypair_resource_policies])
                       .select_from(j)
                       .where((keypair_resource_policies.c.name.in_(names)) &
                              (keypairs.c.access_key == access_key))
                       .order_by(keypair_resource_policies.c.name))
            objs_per_key = OrderedDict()
            for k in names:
                objs_per_key[k] = None
            async for row in conn.execute(query):
                o = cls.from_row(row)
                objs_per_key[row.name] = o
        return tuple(objs_per_key.values())

    @classmethod
    async def batch_load_by_ak(cls, context, access_keys):
        async with context['dbpool'].acquire() as conn:
            j = sa.join(
                keypairs, keypair_resource_policies,
                keypairs.c.resource_policy == keypair_resource_policies.c.name
            )
            query = (sa.select([keypair_resource_policies])
                       .select_from(j)
                       .where((keypairs.c.access_key.in_(access_keys)))
                       .order_by(keypair_resource_policies.c.name))
            objs_per_key = OrderedDict()
            async for row in conn.execute(query):
                o = cls.from_row(row)
                objs_per_key[row.name] = o
        return tuple(objs_per_key.values())


class CreateKeyPairResourcePolicyInput(graphene.InputObjectType):
    default_for_unspecified = graphene.String(required=True)
    total_resource_slots = graphene.JSONString(required=True)
    max_concurrent_sessions = graphene.Int(required=True)
    max_containers_per_session = graphene.Int(required=True)
    idle_timeout = BigInt(required=True)
    max_vfolder_count = graphene.Int(required=True)
    max_vfolder_size = BigInt(required=True)
    allowed_vfolder_hosts = graphene.List(lambda: graphene.String)
    allowed_docker_registries = graphene.List(lambda: graphene.String, required=False)


class ModifyKeyPairResourcePolicyInput(graphene.InputObjectType):
    default_for_unspecified = graphene.String(required=False)
    total_resource_slots = graphene.JSONString(required=False)
    max_concurrent_sessions = graphene.Int(required=False)
    max_containers_per_session = graphene.Int(required=False)
    idle_timeout = BigInt(required=False)
    max_vfolder_count = graphene.Int(required=False)
    max_vfolder_size = BigInt(required=False)
    allowed_vfolder_hosts = graphene.List(lambda: graphene.String, required=False)
    allowed_docker_registries = graphene.List(lambda: graphene.String, required=False)


class CreateKeyPairResourcePolicy(graphene.Mutation):

    class Arguments:
        name = graphene.String(required=True)
        props = CreateKeyPairResourcePolicyInput(required=True)

    ok = graphene.Boolean()
    msg = graphene.String()
    resource_policy = graphene.Field(lambda: KeyPairResourcePolicy)

    @classmethod
    @privileged_mutation(UserRole.SUPERADMIN)
    async def mutate(cls, root, info, name, props):
        data = {
            'name': name,
            'default_for_unspecified':
                DefaultForUnspecified[props.default_for_unspecified],
            'total_resource_slots': ResourceSlot.from_user_input(
                props.total_resource_slots, None),
            'max_concurrent_sessions': props.max_concurrent_sessions,
            'max_containers_per_session': props.max_containers_per_session,
            'idle_timeout': props.idle_timeout,
            'max_vfolder_count': props.max_vfolder_count,
            'max_vfolder_size': props.max_vfolder_size,
            'allowed_vfolder_hosts': props.allowed_vfolder_hosts,
            'allowed_docker_registries': props.allowed_docker_registries,
        }
        insert_query = (keypair_resource_policies.insert().values(data))
        item_query = (
            keypair_resource_policies.select()
            .where(keypair_resource_policies.c.name == name))
        return await simple_db_mutate_returning_item(
            cls, info.context, insert_query,
            item_query=item_query, item_cls=KeyPairResourcePolicy)


class ModifyKeyPairResourcePolicy(graphene.Mutation):

    class Arguments:
        name = graphene.String(required=True)
        props = ModifyKeyPairResourcePolicyInput(required=True)

    ok = graphene.Boolean()
    msg = graphene.String()

    @classmethod
    @privileged_mutation(UserRole.SUPERADMIN)
    async def mutate(cls, root, info, name, props):
        data = {}
        set_if_set(props, data, 'default_for_unspecified',
                   clean_func=lambda v: DefaultForUnspecified[v])
        set_if_set(props, data, 'total_resource_slots',
                   clean_func=lambda v: ResourceSlot.from_user_input(v, None))
        set_if_set(props, data, 'max_concurrent_sessions')
        set_if_set(props, data, 'max_containers_per_session')
        set_if_set(props, data, 'idle_timeout')
        set_if_set(props, data, 'max_vfolder_count')
        set_if_set(props, data, 'max_vfolder_size')
        set_if_set(props, data, 'allowed_vfolder_hosts')
        set_if_set(props, data, 'allowed_docker_registries')
        update_query = (
            keypair_resource_policies.update()
            .values(data)
            .where(keypair_resource_policies.c.name == name))
        return await simple_db_mutate(cls, info.context, update_query)


class DeleteKeyPairResourcePolicy(graphene.Mutation):

    class Arguments:
        name = graphene.String(required=True)

    ok = graphene.Boolean()
    msg = graphene.String()

    @classmethod
    @privileged_mutation(UserRole.SUPERADMIN)
    async def mutate(cls, root, info, name):
        delete_query = (
            keypair_resource_policies.delete()
            .where(keypair_resource_policies.c.name == name)
        )
        return await simple_db_mutate(cls, info.context, delete_query)


async def get_unified_resource_slots(request: web.Request, params: Any, db_conn: SAConnection = None):
    '''
    Calculate unified total_resource_slots for a request and calculates resource limits,
    occupied, and remaining. Currently, domain-/group-/keypair-level resource policies are
    considered.
    '''
    params_checker = t.Dict({
        t.Key('group', default='default'): t.String,
    }).allow_extra('*')
    params_checker.check(params)

    from ai.backend.manager.models import (
        association_groups_users, domains, groups, keypair_resource_policies,
    )

    registry = request.app['registry']
    known_slot_types = await registry.config_server.get_resource_slots()
    domain_name = request['user']['domain_name']
    access_key = request['keypair']['access_key']
    keypair_resource_policy = request['keypair']['resource_policy']

    async def _calculate_slots(conn):
        # Check keypair resource limit.
        keypair_limits = ResourceSlot.from_policy(keypair_resource_policy, known_slot_types)
        keypair_occupied = await registry.get_keypair_occupancy(access_key, conn=conn)
        keypair_remaining = keypair_limits - keypair_occupied

        # Check group resource limit and get group_id.
        j = (groups
             .join(association_groups_users,
                   association_groups_users.c.group_id == groups.c.id)
             .join(keypair_resource_policies,
                   keypair_resource_policies.c.name == groups.c.resource_policy, isouter=True))
        query = (sa.select([groups.c.id, keypair_resource_policies.c.total_resource_slots])
                   .select_from(j)
                   .where(
                       (association_groups_users.c.user_id == request['user']['uuid']) &
                       (groups.c.name == params['group']) &
                       (domains.c.name == domain_name)))
        result = await conn.execute(query)
        row = await result.fetchone()
        if row.id is None:
            raise InvalidAPIParameters('Unknown user group')
        if 'total_resource_slots' in row and row.total_resource_slots is not None:
            group_resource_slots = row.total_resource_slots
        else:
            group_resource_slots = {}
        group_id = row.id
        group_resource_policy = {
            'total_resource_slots': group_resource_slots,
            'default_for_unspecified': DefaultForUnspecified.UNLIMITED
        }
        group_limits = ResourceSlot.from_policy(group_resource_policy, known_slot_types)
        group_occupied = await registry.get_group_occupancy(group_id, conn=conn)
        group_remaining = group_limits - group_occupied

        # Check domain resource limit.
        j = (domains
             .join(keypair_resource_policies,
                   keypair_resource_policies.c.name == domains.c.resource_policy, isouter=True))
        query = (sa.select([keypair_resource_policies.c.total_resource_slots])
                   .select_from(j)
                   .where(domains.c.name == domain_name))
        result = await conn.execute(query)
        row = await result.fetchone()
        if 'total_resource_slots' in row and row.total_resource_slots is not None:
            domain_resource_slots = row.total_resource_slots
        else:
            domain_resource_slots = {}
        domain_resource_policy = {
            'total_resource_slots': domain_resource_slots,
            'default_for_unspecified': DefaultForUnspecified.UNLIMITED
        }
        domain_limits = ResourceSlot.from_policy(domain_resource_policy, known_slot_types)
        domain_occupied = await registry.get_domain_occupancy(domain_name, conn=conn)
        domain_remaining = domain_limits - domain_occupied

        # Take minimum remaining resources. There's no need to merge limits and occupied.
        unified_remaining = keypair_remaining
        for slot in known_slot_types:
            unified_remaining[slot] = min(
                keypair_remaining[slot],
                group_remaining[slot],
                domain_remaining[slot],
            )

        return {
            'keypair_limits': keypair_limits,
            'keypair_occupied': keypair_occupied,
            'keypair_remaining': keypair_remaining,
            'group_limits': group_limits,
            'group_occupied': group_occupied,
            'group_remaining': group_remaining,
            'domain_limits': domain_limits,
            'domain_occupied': domain_occupied,
            'domain_remaining': domain_remaining,
            'unified_remaining': unified_remaining,
            'group_id': group_id,
        }

    if db_conn is not None:
        return await _calculate_slots(db_conn)
    else:
        async with request.app['dbpool'].acquire() as conn, conn.begin():
            return await _calculate_slots(conn)
