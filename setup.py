from setuptools import setup, find_packages

setup(
    name="FunPayAPI",
    version="1.2.0",
    description="Updated and adapted FunPay API client for Telegram bots and automation tools",
    packages=find_packages(where="Funpay AutoSteam"),
    package_dir={"": "Funpay AutoSteam"},
    install_requires=[
        "requests>=2.31.0",
        "requests-toolbelt>=1.0.0",
        "beautifulsoup4>=4.12.0",
        "lxml>=5.0.0",
        "python-dotenv>=1.0.0",
        "colorama>=0.4.6",
    ],
    python_requires=">=3.8",
)
