# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Nova Networks Management Extension
# Copyright 2011 Grid Dynamics
# Copyright 2011 OpenStack LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import math
import netaddr
import webob

from webob import exc

from nova.api.openstack import extensions
from nova import exception
from nova import flags
import nova.network.api

from nova import log as logging
from nova.db.sqlalchemy.session import get_session
from nova.db.sqlalchemy import models


FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'networks')
authorize_view = extensions.extension_authorizer('compute', 'networks:view')


def network_dict(context, network):
    fields = ('id', 'cidr', 'netmask', 'gateway', 'broadcast', 'dns1', 'dns2',
              'cidr_v6', 'gateway_v6', 'label', 'netmask_v6')
    admin_fields = ('created_at', 'updated_at', 'deleted_at', 'deleted',
                    'injected', 'bridge', 'vlan', 'vpn_public_address',
                    'vpn_public_port', 'vpn_private_address', 'dhcp_start',
                    'project_id', 'host', 'bridge_interface', 'multi_host',
                    'priority', 'rxtx_base')
    if network:
        # NOTE(mnaser): We display a limited set of fields so users can know
        #               what networks are available, extra system-only fields
        #               are only visible if they are an admin.
        if context.is_admin:
            fields += admin_fields
        result = dict((field, network[field]) for field in fields)
        if 'uuid' in network:
            result['id'] = network['uuid']
        return result
    else:
        return {}


class NetworkController(object):

    def __init__(self, network_api=None):
        self.network_api = network_api or nova.network.api.API()

    def action(self, req, id, body):
        _actions = {
            'disassociate': self._disassociate,
            'associate': self._associate,
        }

        for action, data in body.iteritems():
            try:
                return _actions[action](req, id, body)
            except KeyError:
                msg = _("Network does not have %s action") % action
                raise exc.HTTPBadRequest(explanation=msg)

        raise exc.HTTPBadRequest(explanation=_("Invalid request body"))

    def _disassociate(self, request, network_id, body):
        context = request.environ['nova.context']
        authorize(context)
        LOG.debug(_("Disassociating network with id %s"), network_id)
        try:
            self.network_api.disassociate(context, network_id)
        except exception.NetworkNotFound:
            raise exc.HTTPNotFound(_("Network not found"))
        return exc.HTTPAccepted()

    def index(self, req):
        context = req.environ['nova.context']
        authorize_view(context)
        networks = self.network_api.get_all(context)
        result = [network_dict(context, net_ref) for net_ref in networks]
        return {'networks': result}

    def show(self, req, id):
        context = req.environ['nova.context']
        authorize_view(context)
        LOG.debug(_("Showing network with id %s") % id)
        try:
            network = self.network_api.get(context, id)
        except exception.NetworkNotFound:
            raise exc.HTTPNotFound(_("Network not found"))
        return {'network': network_dict(context, network)}

    def delete(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
        LOG.info(_("Deleting network with id %s") % id)
        try:
            self.network_api.delete(context, id)
        except exception.NetworkNotFound:
            raise exc.HTTPNotFound(_("Network not found"))
        return exc.HTTPAccepted()

    def create(self, req, body):
        context = req.environ['nova.context']
        authorize(context)
        if not body:
            raise exc.HTTPUnprocessableEntity()

        if not "network" in body:
            raise exc.HTTPUnprocessableEntity()

        network_params = body["network"]
        str_args = ("bridge", "bridge_interface",
                    "cidr", "cidr_v6", "dns1", "dns2",
                    "fixed_cidr", "gateway", "gateway_v6",
                    "label", "multi_host", "priority",
                    "project_id")
        int_args = ("network_size", "num_networks",
                    "vlan_start", "vpn_start")
        ctor_args = str_args + int_args
        for key in int_args:
            try:
                network_params[key] = int(network_params[key])
            except ValueError:
                raise exc.HTTPBadRequest(
                    explanation=_("%s must be an integer") % key)
            except KeyError:
                pass

        # check for certain required inputs
        if not network_params["label"]:
            raise exc.HTTPBadRequest(
                explanation=_("Network label is required"))
        if not (network_params["cidr"] or network_params["cidr_v6"]):
            raise exc.HTTPBadRequest(
                explanation=_("cidr or cidr_v6 is required"))

        kwargs = dict(((k, network_params.get(k, None))
                       for k in ctor_args))

        bridge = kwargs["bridge"] or FLAGS.flat_network_bridge
        if not bridge:
            bridge_required = ['nova.network.manager.FlatManager',
                               'nova.network.manager.FlatDHCPManager']
            if FLAGS.network_manager in bridge_required:
                raise exc.HTTPBadRequest(
                    explanation=_("bridge is required"))
        kwargs["bridge"] = bridge

        bridge_interface = (kwargs["bridge_interface"] or
                            FLAGS.flat_interface or
                            FLAGS.vlan_interface)
        if not bridge_interface:
            interface_required = ['nova.network.manager.VlanManager']
            if FLAGS.network_manager in interface_required:
                raise exc.HTTPBadRequest(
                    explanation=_("bridge_interface is required"))
        kwargs["bridge_interface"] = bridge_interface

        # sanitize other input using FLAGS if necessary
        num_networks = kwargs["num_networks"] or FLAGS.num_networks
        network_size = kwargs["network_size"]
        cidr = kwargs["cidr"]
        if not network_size and cidr:
            fixnet = netaddr.IPNetwork(cidr)
            each_subnet_size = fixnet.size / num_networks
            if each_subnet_size > FLAGS.network_size:
                network_size = FLAGS.network_size
                subnet = 32 - int(math.log(network_size, 2))
                oversize_msg = _(
                    'Subnet(s) too large, defaulting to /%s.'
                    '  To override, specify network_size flag.') % subnet
                LOG.warn(oversize_msg)
            else:
                network_size = fixnet.size
        kwargs["num_networks"] = num_networks
        kwargs["network_size"] = network_size

        kwargs["multi_host"] = kwargs["multi_host"] or FLAGS.multi_host
        kwargs["vlan_start"] = kwargs["vlan_start"] or FLAGS.vlan_start
        kwargs["vpn_start"] = kwargs["vpn_start"] or FLAGS.vpn_start
        kwargs["dns1"] = kwargs["dns1"] or FLAGS.flat_network_dns
        kwargs["network_size"] = kwargs["network_size"] or FLAGS.network_size

        if kwargs["fixed_cidr"]:
            kwargs["fixed_cidr"] = netaddr.IPNetwork(fixed_cidr)

        # create the network
        LOG.debug(_("Creating network with label %s") % kwargs["label"])
        try:
            networks = self.network_api.create(context, **kwargs)
        except Exception as ex:
            raise exc.HTTPBadRequest(
                explanation=_("Cannot create network. %s") %
                getattr(ex, "value", str(ex)))
        result = [network_dict(context, net_ref) for net_ref in networks]
        return  {'networks': result}

    def _associate(self, req, network_id, body):
        context = req.environ['nova.context']
        authorize(context)
        if not body:
            raise exc.HTTPUnprocessableEntity()

        project_id = body["associate"]
        LOG.debug(_("Associating network %s with project %s") %
                  (network_id, project_id))
        session = get_session()
        count = session.query(models.Network).filter_by(
            uuid=network_id, project_id=None).update({
                "project_id": project_id
            })
        if count:
            return webob.Response(status_int=202)
        raise exc.HTTPBadRequest(
            explanation=_("Cannot associate network %s with project %s") %
            (network_id, project_id))

    def add(self, req, body):
        return self._associate(
            req, body.get('id', None),
            {'associate': context.project_id})

    def detail(self, req):
        return self.index(req)


class Networks(extensions.ExtensionDescriptor):
    """Admin-only Network Management Extension."""

    name = "GDNetworks"
    alias = "gd-networks"
    namespace = "http://docs.openstack.org/compute/ext/networks/api/v1.1"
    updated = "2012-07-06T00:00:00+00:00"

    def get_resources(self):
        member_actions = {'action': 'POST'}
        collection_actions = {'add': 'POST', 'detail': 'GET'}
        res = extensions.ResourceExtension(
            'gd-networks',
            NetworkController(),
            member_actions=member_actions,
            collection_actions=collection_actions)
        return [res]
