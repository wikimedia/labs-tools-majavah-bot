from setuptools import find_packages, setup

setup(
    name="majavah-bot",
    version="1",
    author="Taavi Väänänen",
    author_email="hi@taavi.wtf",
    license="MIT",
    packages=find_packages(),
    entry_points={"console_scripts": ["majavah-bot = majavahbot.cli:main"]},
    description="A Wikimedia editing bot",
    install_requires=[
        "dateparser",
        "mwparserfromhell",
        "pymysql",
        "pywikibot",
        "sseclient",
        "requests",
        "toolforge",
    ],
    package_data={"majavahbot": ["py.typed"]},
)
