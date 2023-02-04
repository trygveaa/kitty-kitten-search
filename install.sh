#!/bin/bash

if [[ -z $1 ]];
then
	mv $(pwd) ~/.config/kitty
else
	mv $(pwd) $1
fi
