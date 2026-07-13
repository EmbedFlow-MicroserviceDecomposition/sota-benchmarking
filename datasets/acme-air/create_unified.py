# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import os
import shutil

def create_eclipse_project(base_dir):
    dataset_dir = os.path.dirname(base_dir)
    unified_dir = os.path.join(dataset_dir, 'acmeair-unified')
    src_dir = os.path.join(unified_dir, 'src')
    
    # 1. Create directory structure
    os.makedirs(src_dir, exist_ok=True)
    
    # 2. Find all src/main/java directories and copy them over
    for root, dirs, files in os.walk(base_dir):
        # Skip the unified directory itself
        if 'acmeair-unified' in root:
            continue
            
        if root.endswith(os.path.join('src', 'main', 'java')):
            print(f"Copying sources from: {root}")
            # The contents of src/main/java are usually packages (e.g., 'com')
            for item in os.listdir(root):
                s = os.path.join(root, item)
                d = os.path.join(src_dir, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)

    # 3. Create .project file for Eclipse
    project_content = """<?xml version="1.0" encoding="UTF-8"?>
<projectDescription>
	<name>acmeair-unified</name>
	<comment></comment>
	<projects>
	</projects>
	<buildSpec>
		<buildCommand>
			<name>org.eclipse.jdt.core.javabuilder</name>
			<arguments>
			</arguments>
		</buildCommand>
	</buildSpec>
	<natures>
		<nature>org.eclipse.jdt.core.javanature</nature>
	</natures>
</projectDescription>
"""
    with open(os.path.join(unified_dir, '.project'), 'w') as f:
        f.write(project_content)

    # 4. Create .classpath file for Eclipse
    classpath_content = """<?xml version="1.0" encoding="UTF-8"?>
<classpath>
	<classpathentry kind="src" path="src"/>
	<classpathentry kind="con" path="org.eclipse.jdt.launching.JRE_CONTAINER"/>
	<classpathentry kind="output" path="bin"/>
</classpath>
"""
    with open(os.path.join(unified_dir, '.classpath'), 'w') as f:
        f.write(classpath_content)

    print(f"\nSuccessfully created Eclipse Java Project at: {unified_dir}")
    print("You can now Import this directory into Eclipse as an 'Existing Project into Workspace'.")

if __name__ == "__main__":
    acmeair_base = os.path.join(os.path.dirname(__file__), 'acmeair')
    create_eclipse_project(acmeair_base)
