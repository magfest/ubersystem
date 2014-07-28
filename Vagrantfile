# -*- mode: ruby -*-

VAGRANTFILE_API_VERSION = "2"

Vagrant.configure(VAGRANTFILE_API_VERSION) do |config|
    config.vm.box = "Ubuntu 14.04"
    config.vm.box_url = "https://cloud-images.ubuntu.com/vagrant/trusty/current/trusty-server-cloudimg-i386-vagrant-disk1.box"
    config.vm.network :forwarded_port, guest: 8282, host: 8282

    # TODO: this if/else both have the same code, which seems outdated/wrong
    if Vagrant::Util::Platform.windows?
        config.vm.synced_folder ".", "/home/vagrant/magfest"
    else
        config.vm.synced_folder ".", "/home/vagrant/magfest"
    end

    config.vm.provision :shell, :path => "vagrant/vagrant.sh"

    config.vm.provider :virtualbox do |vb|
        vb.customize ["setextradata", :id, "VBoxInternal2/SharedFoldersEnableSymlinksCreate/home_vagrant_magfest", "1"]
    end
end
