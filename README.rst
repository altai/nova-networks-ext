To enable this extension, add to /etc/nova/nova.conf:

::

    vlan_interface = eth0
    osapi_compute_extension = nova.api.openstack.compute.contrib.standard_extensions
    osapi_compute_extension = nova_networks.networks.Networks
