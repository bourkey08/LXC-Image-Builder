import os, shutil, subprocess, time, sys, json

#Called when the program is run in interactive mode, ensures the desktop enviroment is setup and the required files and folders exist
def InitializeDesktop():
    #First check if a config file exists and if it does not create a sample config
    if not os.path.exists('config.json'):
        config  = {
            'WorkingDirectory': 'Temp',
            'Containers': {
                'Templates': 'Containers/Templates',
                'Images': 'Containers/Images'
            }
        }

        with open('config.json', 'w') as fil:
            fil.write(json.dumps(config, indent=4))

    else:
        config = json.load(open('config.json', 'r'))

    #If the working directory exists, remove it and then recreate. Also need to create a path that we will map between host and vm
    if os.path.exists(config['WorkingDirectory']):
        shutil.rmtree(config['WorkingDirectory'])

    os.makedirs(config['WorkingDirectory'])
    os.makedirs(os.path.join(config['WorkingDirectory'], 'Shared'))

    #Now lets make a vagrant file in the working directory
    with open(os.path.join(config['WorkingDirectory'], 'Vagrantfile'), 'w') as fil:
        fil.write('''# -*- mode: ruby -*-\n# vi: set ft=ruby :
                    Vagrant.configure("2") do |config|
                        config.vm.box = "generic/ubuntu2010"
                        config.vm.synced_folder "Shared", "/mapped"
                        config.vm.provider "virtualbox" do |vb|
                            vb.memory = "2048"
                        end
                    end
                    ''')

    #Make sure folders for containers exists
    if not os.path.exists(os.path.join(config['Containers']['Templates'])):
        os.makedirs(os.path.join(config['Containers']['Templates']))

    if not os.path.exists(os.path.join(config['Containers']['Images'])):
        os.makedirs(os.path.join(config['Containers']['Images']))

    return config

#This class is called when the user runs the python file to start creating the images/containers
class BuildImages():
    #Run a command and prints output as its returned
    def RunCmd(self, cmd, workingdir=False):
        #If no working directory was provided run in the normal working directory
        if workingdir == False:
            workingdir = self.config['WorkingDirectory']

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=workingdir)
        while proc.poll() == None:
            line = proc.stdout.readline()
            if line != b'':
                print (line.decode('ascii', 'ignore').rstrip('\r\n').rstrip('\n'))

        line = proc.stdout.readline()
        if line != b'':
            print (line.decode('ascii', 'ignore'))        

    def __init__(self, config):
        #Copy config to be a member of this object
        self.config = config

        #Copy this script to the shared directory so it can be run on the vm
        shutil.copy(sys.argv[0], os.path.join(self.config['WorkingDirectory'], 'Shared', os.path.split(sys.argv[0])[1]))
        Templates = []

        #Also copy all the templates that do not have an image present for there current version in the images directory to the shared directory so that they can be referenced when creating the images
        for template in os.listdir(self.config['Containers']['Templates']):
            #If a folder for the template does not exist in images directory, make one now
            if not os.path.exists(os.path.join(self.config['Containers']['Images'], template)):
                os.makedirs(os.path.join(self.config['Containers']['Images'], template))

            #Now load the config for each template
            with open(os.path.join(self.config['Containers']['Templates'], template, 'config.json'), 'r') as fil:
                template_config = json.loads(fil.read())

            #And now make sure a folder exists for the Major/Minor/Patch
            releaseroot = os.path.join(self.config['Containers']['Images'], template, *[str(x) for x in template_config['Version'][:3]])
            if not os.path.exists(releaseroot):
                os.makedirs(releaseroot)

            #Finally if the current template version does not have an image available, copy it to the temp directory so we can make one
            if not os.path.exists(os.path.join(releaseroot, template + '_' + '.'.join([str(x) for x in template_config['Version']]) + '.tar.gz')):
                #If we are going to make an image for this template add an entry to templates array so we dont need to load its config again to rename/move the image
                Templates += [(template, releaseroot, template_config['Version'])]

                shutil.copytree(os.path.join(self.config['Containers']['Templates'], template), '\\\\?\\' + os.path.realpath(os.path.join(self.config['WorkingDirectory'], 'Shared', 'Templates', template)))

        if len(Templates) > 0:
            #Now lets create the vm, fetching the image if required and then start it
            self.RunCmd('vagrant up')  

            self.RunCmd('vagrant ssh -c "sudo python3 /mapped/ImageBuilder.py buildimages"') 

            #Now after creating all images we need to copy the output images to the correct location with the correct names
            #Also copy all the templates that do not have an image present for there current version in the images directory to the shared directory so that they can be referenced when creating the images
            for template in Templates:

                outputfilename = os.path.join(template[1], template[0] + '_' + '.'.join([str(x) for x in template[2]]) + '.tar.gz')
                
                #If an image was successfully created for this container, copy it to output now
                if os.path.exists(os.path.join(self.config['WorkingDirectory'], 'Shared', template[0] + '_Image')):

                    #Move file to the images directory with the correct filename
                    shutil.move(os.path.join(self.config['WorkingDirectory'], 'Shared', template[0] + '_Image'), outputfilename)

    #The run function is called to actually create the images/containers
    def run(self):
        self.Cleanup()

    #Called by run function before exiting, removes any temp files and destroys the vm
    def Cleanup(self):
        self.RunCmd('vagrant halt')
        self.RunCmd('vagrant destroy -f')

        shutil.rmtree('\\\\?\\' + self.config['WorkingDirectory'])

#This is called after the host vm boots inside vagrant
class CreateImages():
    #Run a command and prints output as its returned
    def RunCmd(self, cmd):
        proc = subprocess.Popen(['bash', '-c', cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        while proc.poll() == None:
            line = proc.stdout.readline()
            if line != b'':
                print (line.decode('ascii', 'ignore').rstrip('\r\n').rstrip('\n'))

        line = proc.stdout.readline()
        if line != b'':
            print (line.decode('ascii', 'ignore'))

    def __init__(self):
        #Cd into the mapped folder
        os.chdir('/mapped')

        #This isent strictly nessesary, just here to solve a weird intermittent issue where this script started before lxc had started
        time.sleep(30)
        
        self.RunCmd('apt-get update')
        
        time.sleep(30)

        #Initilize lxd with default settings
        self.RunCmd('lxd init --auto')   

    #Define a run function, this will be called after initilization and will handle the actual creation of the images
    def run(self):
        #Iterate over the list of templates and for each template create a container, push in all files, run provision scripts and then publish/export
        for template in os.listdir('Templates'):
            if not os.path.join('Templates', template):
                print ('Skipping: ' + template)
                continue

            print ('Creating Image: ' + template)
            with open(os.path.join('Templates', template, 'config.json'), 'r') as fil:#Load the config for this template
                template_config = json.loads(fil.read())

            #Launch an lxc container using the specified base image
            self.RunCmd('lxc launch {image} {containername}'.format(image=template_config['Base_Image'], containername=template))
            time.sleep(30)#Wait 30 seconds to make sure the container has had time to start up and get an IP address/DNS

            #Make a temp directory in the root of the container that we can copy required scripts into
            self.RunCmd('lxc exec {image} -- bash -c "mkdir /SetupTemp"'.format(image=template))

            #Iterate over provision scripts and add each of them to to temp folder
            for script in template_config['Provision_Scripts']:      
                self.RunCmd('lxc file push "{src}" "{image}/SetupTemp/"'.format(image=template, src=os.path.join('Templates', template, script), dst=script))

            #Now if there are any files in root, iterate over all files and add them to the container relative to /
            for a in os.walk(os.path.join('Templates', template, 'Root')):
                for b in a[1]:
                    self.RunCmd('lxc exec {image} -- bash -c "mkdir /{dir}"'.format(image=template, dir=os.path.join(a[0].replace(os.path.join('Templates', template, 'Root'), ''), b)))

                for b in a[2]:
                    self.RunCmd('lxc file push {src} {image}/{dst}'.format(image=template, src=os.path.join(a[0], b), dst=os.path.join(a[0].replace(os.path.join('Templates', template, 'Root'), ''), b)))

            #Now run each of the provision scripts in order
            for script in template_config['Provision_Scripts']:
                print ('Running Provision Script: ' + script)
                self.RunCmd('lxc exec {image} /SetupTemp/{script}'.format(image=template, script=script))

            #And then remove the setuptemp folder folder
            self.RunCmd('lxc exec {image} "rm -R /SetupTemp"'.format(image=template))

            #Add cronjobs for all start entrys for this container
            if len(template_config['Startup_Commands']) > 0:
                counter = 0#Keep track of a unique number we can use to number the cron jobs if the template has not specified a name

                for startupentry in template_config['Startup_Commands']:
                    cmd, user, startin, name = startupentry['Command'], startupentry['RunAs'], startupentry['StartIn'], startupentry['Name']

                    #If the command is not blank then add it. This is really just here to allow the basic template to contain a command entry without it doing anything
                    if cmd != '':
                        #Define a list that we will add lines to and then write all at once
                        StartupEntrys = []

                        #If no user is specified default to root
                        if user == '':
                            user = 'root'

                        #If a start in was specified, add a home argument to the top of the cronjob
                        if startin != '':
                            StartupEntrys.append('HOME=' + startin)

                        #If a name was not specified, use the next entry
                        if name == '':
                            name = str(counter)
                            counter += 1
                             
                        #And add the command to the list of startup entrys
                        StartupEntrys.append('@reboot {0} {1}'.format(user, cmd))

                        #Create a temp file for the cron entry and write the entrys to it
                        with open('crontabtemp','w') as fil:
                            fil.write('\n'.join(StartupEntrys) + '\n')

                        #Now push that file to the correct location in the container
                        self.RunCmd('lxc file push crontabtemp {image}/etc/cron.d/{name}'.format(image=template, name=name))

                        #Chmod it to 755
                        self.RunCmd('lxc exec {image} -- bash -c "chmod 755 /etc/cron.d/{name}"'.format(image=template, name=name))

                        #If the command ends in .sh and contains no spaces assume its a shell/bash script and chmod it to 755 so it will actually run
                        if cmd.endswith('.sh') and ' ' not in cmd:
                            self.RunCmd('lxc exec {image} -- bash -c "chmod 755 {cmd}"'.format(image=template, cmd=cmd))

                        #And remove the temp file
                        os.remove('crontabtemp')

            #Last thing to do before we export an image, remove the setup folder
            self.RunCmd('lxc exec {image} -- bash -c "rm -R /SetupTemp"'.format(image=template))

            #Now lets shutdown the container and make an image
            self.RunCmd('lxc stop {image}'.format(image=template))            
            self.RunCmd('lxc publish --force {image} --alias {image}_Image'.format(image=template))

            self.RunCmd('lxc image export {image}_Image {image}_Image'.format(image=template))

            #Now lets remove the container and image
            self.RunCmd('lxc delete {image}'.format(image=template))
            self.RunCmd('lxc image delete {image}_Image'.format(image=template))

#Called to create a blank image template
def AddBlankTemplate(config):
    #List of available images
    AvailImages = [
        ('Ubuntu LTS 10', 'images:ubuntu/10.04/cloud'),
        ('Ubuntu LTS 11', 'images:ubuntu/11.04/cloud'),
        ('Ubuntu LTS 12', 'images:ubuntu/12.04/cloud'),
        ('Ubuntu LTS 13', 'images:ubuntu/13.04/cloud'),
        ('Ubuntu LTS 14', 'images:ubuntu/14.04/cloud'),
        ('Ubuntu LTS 15', 'images:ubuntu/15.04/cloud'),
        ('Ubuntu LTS 16', 'images:ubuntu/16.04/cloud'),
        ('Ubuntu LTS 17', 'images:ubuntu/17.04/cloud'),
        ('Ubuntu LTS 18', 'images:ubuntu/18.04/cloud'),
        ('Ubuntu LTS 19', 'images:ubuntu/19.04/cloud'),
        ('Ubuntu LTS 20', 'images:ubuntu/20.04/cloud'),
        ('Ubuntu LTS 21', 'images:ubuntu/21.04/cloud')
    ]

    #Clear the console window
    os.system('cls')

    while True:
        #Now request the name of the template
        print ('New Template Name')
        TemplateName = input('> ')

        #If the templates does not yet exist, then break out of the loop and lets make it, otherwise ask again
        if not os.path.exists(os.path.join(config['Containers']['Templates'], TemplateName)):
            break                

        else:#Otherwise, the template exists, ask the user what they want to do
            os.system('cls')
            print ('The specified template already exists, try again?')
            print ('')
            resp = input('Y/N> ')

            #If the response was not true, exit
            if resp.lower() != 'y':
                print ('Exiting')
                time.sleep(5)
                exit(0)

    #Now ask the user to pick a base image
    while True:
        #Clear the console window
        os.system('cls')

        print ('Please select the base image to use for the container')
        print ('\n')

        for i in range(0, len(AvailImages)):
            print ('{0}: {1}'.format(i + 1, AvailImages[i][0]))

        print ('')
        selection = input('> ')

        if selection not in [str(x + 1) for x in range(0, len(AvailImages))]:
            os.system('cls')
            print ('Invalid Image Selected, Try Again?')
            print ('')
            resp = input('Y/N> ')

            #If the response was not true, exit
            if resp.lower() != 'y':
                print ('Exiting')
                time.sleep(5)
                exit(0)
        else:
            BaseImage = AvailImages[int(selection)-1][1]
            break

    #Get the root folder for this template
    rootfolder = os.path.join(config['Containers']['Templates'], TemplateName)

    #Make a folder for the template
    os.makedirs(rootfolder)

    #And also make a subfolder for files that should be directly included in the template
    os.makedirs(os.path.join(rootfolder, 'Root'))

    #Define a config for this template
    templateconfig = {
        "Version": [0, 1, 0, 1],
        'Base_Image': BaseImage,
        'Provision_Scripts': [
            'provision.sh'
        ],
        'Startup_Commands': [
            {   
                "Name": "",
                "Command": "",
                "RunAs": "",
                "StartIn": ""
            }
        ]
    }

    #Write out the template config file
    with open(os.path.join(rootfolder, 'config.json'), 'w') as fil:
        fil.write(json.dumps(templateconfig, indent=4))

    #And also write out a template provision shell script, this will be run inside the container
    with open(os.path.join(rootfolder, 'provision.sh'), 'w') as fil:
        fil.write('''#This script is run inside the container inorder to build the image, the script is then deleted before exporting the image''')

    print ('Template Created')
    exit(0)


if __name__ == '__main__':
    #If there is a command line argument
    if len(sys.argv) > 1:
        if sys.argv[1] == 'buildimages':
            CreateImages().run()
            exit(0)

        elif sys.argv[1].lower() == 'build':
            #Load the config, this also creates directorys if they are missing
            config = InitializeDesktop()

            BuildImages(config).run()
            exit(0)

        else:
            print ('Unknown argument')
            exit(1)

    #Otherwise run in interactive mode
    else:      
        #Load the config, this also creates directorys if they are missing
        config = InitializeDesktop()

        print ('Select an option')
        print ('    1: Add Template')
        print ('    2: Build Images')

        action = input('> ')

        #User wants to add a blank template
        if action == '1':            
            AddBlankTemplate(config)

        #User wants to build images for templates
        elif action == '2':
            BuildImages(config).run()
            exit(0)

        else:
            print ('Invalid Selection Exiting')
            time.sleep(10)
            exit()