%global with_doc 0

%if ! (0%{?fedora} > 12 || 0%{?rhel} > 5)
%{!?python_sitelib: %global python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())")}
%endif


Name:             nova-networks-ext
Version:          1.0
Release:          0
Summary:          A common networks-ext server
License:          Apache 2.0
Vendor:           Grid Dynamics International, Inc.
URL:              http://www.griddynamics.com/openstack
Group:            Development/Languages/Python

Source0:          %{name}-%{version}.tar.gz
BuildRoot:        %{_tmppath}/%{name}-%{version}-build
BuildRequires:    python-devel
BuildRequires:    python-setuptools
BuildArch:        noarch
Requires:         openstack-nova-essex-api


%description
Network management extension for nova.


%prep
%setup -q -n %{name}-%{version}


%build
%{__python} setup.py build


%install
%__rm -rf %{buildroot}

%{__python} setup.py install -O1 --skip-build --prefix=%{_prefix} --root=%{buildroot}


%clean
%__rm -rf %{buildroot}

%post
if [ "$1" = "2" ]; then # upgrade
    exit 0
fi

if ! grep -q osapi_compute_extension /etc/nova/nova.conf; then
    echo "osapi_compute_extension = nova.api.openstack.compute.contrib.standard_extensions" >> /etc/nova/nova.conf
fi
if ! grep -q nova_networks.networks.Networks /etc/nova/nova.conf; then
    echo "osapi_compute_extension = nova_networks.networks.Networks" >> /etc/nova/nova.conf
    /sbin/service nova-api condrestart
fi
exit 0

%postun
if [ "$1" = "0" ]; then # uninstallation
    if grep -q nova_networks.networks.Networks /etc/nova/nova.conf; then
        sed -i '/nova_networks.networks.Networks/d' /etc/nova/nova.conf
    else
        exit 0
    fi
fi
/sbin/service nova-api condrestart
exit 0

%files
%defattr(-,root,root,-)
%doc README.rst COPYING
%{python_sitelib}/*


%changelog
